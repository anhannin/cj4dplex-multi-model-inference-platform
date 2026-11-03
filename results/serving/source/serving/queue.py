"""One bounded FIFO and one inference thread per model; no cross-model state."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import logging
import time
import uuid

LOG = logging.getLogger("serving")


class QueueFull(Exception):
    pass


class QueueClosed(Exception):
    pass


@dataclass
class Job:
    payload: object
    future: asyncio.Future
    enqueued: float
    request_id: str
    sequence: int


class InferenceQueue:
    def __init__(self, factory, *, capacity, name):
        if capacity < 1:
            raise ValueError("Queue capacity must be positive")
        self.name = name
        self.factory = factory
        self.queue = asyncio.Queue(maxsize=capacity)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=name)
        self.backend = None
        self.consumer = None
        self.accepting = False
        self.sequence = 0

    @property
    def waiting_count(self):
        return self.queue.qsize()

    async def start(self):
        if self.consumer is not None:
            raise RuntimeError("Queue already started")
        self.backend = await asyncio.get_running_loop().run_in_executor(
            self.executor, self.factory
        )
        self.accepting = True
        self.consumer = asyncio.create_task(
            self._consume(), name=self.name + "-consumer"
        )
        LOG.info(
            json.dumps(
                {"event": "model_ready", "model": self.name, "time": time.time()}
            )
        )

    async def submit(self, payload):
        if not self.accepting:
            raise QueueClosed()
        future = asyncio.get_running_loop().create_future()
        self.sequence += 1
        job = Job(payload, future, time.perf_counter(), uuid.uuid4().hex, self.sequence)
        try:
            self.queue.put_nowait(job)
        except asyncio.QueueFull:
            raise QueueFull() from None
        return await future

    async def _consume(self):
        loop = asyncio.get_running_loop()
        while True:
            job = await self.queue.get()
            try:
                if job is None:
                    return
                if job.future.cancelled():
                    continue
                started = time.perf_counter()
                wait_ms = (started - job.enqueued) * 1000
                LOG.info(
                    json.dumps(
                        {
                            "event": "inference_started",
                            "model": self.name,
                            "request_id": job.request_id,
                            "sequence": job.sequence,
                            "time": time.time(),
                            "queue_wait_ms": wait_ms,
                        }
                    )
                )
                try:
                    result = await loop.run_in_executor(
                        self.executor, self.backend, job.payload
                    )
                    if not isinstance(result, dict):
                        raise TypeError("Backend must return a dictionary")
                except Exception as error:
                    LOG.error(
                        json.dumps(
                            {
                                "event": "inference_error",
                                "model": self.name,
                                "request_id": job.request_id,
                                "sequence": job.sequence,
                                "time": time.time(),
                                "error_type": type(error).__name__,
                            }
                        )
                    )
                    if not job.future.done():
                        # Do not expose the live consumer coroutine frame in a Future traceback.
                        job.future.set_exception(error.with_traceback(None))
                else:
                    processing_ms = (time.perf_counter() - started) * 1000
                    LOG.info(
                        json.dumps(
                            {
                                "event": "inference_finished",
                                "model": self.name,
                                "request_id": job.request_id,
                                "sequence": job.sequence,
                                "time": time.time(),
                                "processing_ms": processing_ms,
                            }
                        )
                    )
                    if not job.future.done():
                        job.future.set_result(
                            {
                                **result,
                                "request_id": job.request_id,
                                "sequence": job.sequence,
                                "queue_wait_ms": wait_ms,
                                "processing_ms": processing_ms,
                            }
                        )
            finally:
                self.queue.task_done()
                # Do not retain the last request/image/result while idle.
                job = None

    async def close(self):
        self.accepting = False
        if self.consumer is not None:
            await self.queue.put(None)
            await self.consumer
            self.consumer = None
        self.backend = None
        self.executor.shutdown(wait=True)
