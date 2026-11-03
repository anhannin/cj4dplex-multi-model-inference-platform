import asyncio
import threading
import unittest
from serving.queue import InferenceQueue, QueueFull, QueueClosed


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_one_consumer_and_result_pairing(self):
        order, threads = [], []
        loaded = []

        def factory():
            loaded.append(threading.get_ident())

            def infer(value):
                threads.append(threading.get_ident())
                order.append(value)
                return {"echo": value}

            return infer

        queue = InferenceQueue(factory, capacity=8, name="test")
        await queue.start()
        try:
            replies = await asyncio.gather(*(queue.submit(i) for i in range(5)))
            self.assertEqual(order, list(range(5)))
            self.assertEqual([r["echo"] for r in replies], list(range(5)))
            self.assertEqual([r["sequence"] for r in replies], [1, 2, 3, 4, 5])
            self.assertEqual(len(loaded), 1)
            self.assertEqual(set(threads), set(loaded))
            self.assertTrue(
                all(
                    r["queue_wait_ms"] >= 0 and r["processing_ms"] >= 0 for r in replies
                )
            )
        finally:
            await queue.close()

    async def test_capacity_rejects_only_when_waiting_queue_full(self):
        started, release = threading.Event(), threading.Event()

        def infer(value):
            started.set()
            release.wait(5)
            return {"echo": value}

        queue = InferenceQueue(lambda: infer, capacity=1, name="test")
        await queue.start()
        first = asyncio.create_task(queue.submit("first"))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        second = asyncio.create_task(queue.submit("second"))
        await asyncio.sleep(0.01)
        try:
            self.assertEqual(queue.waiting_count, 1)
            with self.assertRaises(QueueFull):
                await queue.submit("third")
        finally:
            release.set()
            replies = await asyncio.gather(first, second)
            await queue.close()
        self.assertEqual([r["echo"] for r in replies], ["first", "second"])
        self.assertGreater(replies[1]["queue_wait_ms"], 0)

    async def test_cancelled_waiting_request_is_not_executed(self):
        started, release = threading.Event(), threading.Event()
        seen = []

        def infer(value):
            seen.append(value)
            if value == "first":
                started.set()
                release.wait(5)
            return {"echo": value}

        queue = InferenceQueue(lambda: infer, capacity=4, name="test")
        await queue.start()
        first = asyncio.create_task(queue.submit("first"))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        cancelled = asyncio.create_task(queue.submit("cancelled"))
        await asyncio.sleep(0.01)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled
        release.set()
        await first
        await queue.submit("last")
        await queue.close()
        self.assertEqual(seen, ["first", "last"])

    async def test_errors_do_not_orphan_other_requests(self):
        def infer(value):
            if value == "bad":
                raise ValueError("test error")
            return {"echo": value}

        queue = InferenceQueue(lambda: infer, capacity=4, name="test")
        await queue.start()
        with self.assertRaises(ValueError):
            await queue.submit("bad")
        self.assertEqual((await queue.submit("good"))["echo"], "good")
        await queue.close()
        with self.assertRaises(QueueClosed):
            await queue.submit("late")

    async def test_independent_queues_do_not_block_each_other(self):
        started, release = threading.Event(), threading.Event()

        def slow(value):
            started.set()
            release.wait(5)
            return {"echo": value}

        qwen = InferenceQueue(lambda: slow, capacity=4, name="qwen")
        yolo = InferenceQueue(lambda: lambda x: {"echo": x}, capacity=4, name="yolo")
        await qwen.start()
        await yolo.start()
        first = asyncio.create_task(qwen.submit("qwen"))
        self.assertTrue(await asyncio.to_thread(started.wait, 2))
        try:
            reply = await asyncio.wait_for(yolo.submit("yolo"), timeout=1)
            self.assertEqual(reply["echo"], "yolo")
            self.assertFalse(first.done())
        finally:
            release.set()
            await first
            await qwen.close()
            await yolo.close()

    async def test_load_failure_propagates_and_cleanup_is_safe(self):
        def fail():
            raise RuntimeError("load failed")

        queue = InferenceQueue(fail, capacity=1, name="test")
        with self.assertRaises(RuntimeError):
            await queue.start()
        await queue.close()

    def test_capacity_must_be_positive(self):
        with self.assertRaises(ValueError):
            InferenceQueue(lambda: None, capacity=0, name="test")

    async def test_bad_backend_result_does_not_hang_http_waiter(self):
        queue = InferenceQueue(lambda: lambda x: None, capacity=1, name="test")
        await queue.start()
        try:
            with self.assertRaises(TypeError):
                await asyncio.wait_for(queue.submit("test"), timeout=1)
        finally:
            await asyncio.wait_for(queue.close(), timeout=1)
