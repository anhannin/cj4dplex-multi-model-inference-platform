"""CPU contract checks; real ROS/DDS/GPU tests run separately on Spark."""

import ast
import itertools
import json
from pathlib import Path
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import time

ROOT = Path(__file__).resolve().parents[1] / "ros2"


class ROSNodeContracts(unittest.TestCase):
    def source(self, kind):
        return (ROOT / (kind + "_node.py")).read_text()

    def callback(self, kind):
        tree = ast.parse(self.source(kind))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method = next(
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "_on_request"
        )
        namespace = {"queue": queue, "time": time, "json": json}
        exec(
            compile(ast.Module(body=[method], type_ignores=[]), "<callback>", "exec"),
            namespace,
        )
        return namespace["_on_request"]

    def fake_node(self, capacity=8):
        logger = Mock()
        return SimpleNamespace(
            requests=queue.Queue(capacity),
            sequence=itertools.count(1),
            get_logger=lambda: logger,
            logger=logger,
        )

    def test_two_separate_standalone_nodes_and_native_calls(self):
        for kind, call in [("qwen", "generate"), ("yolo", "predict")]:
            with self.subTest(kind=kind):
                tree = ast.parse(self.source(kind))
                classes = [
                    n for n in tree.body if isinstance(n, ast.ClassDef) and n.bases
                ]
                self.assertEqual(len(classes), 1)
                self.assertEqual(classes[0].bases[0].id, "Node")
                self.assertFalse(any("backend" in n.name.lower() for n in classes))
                methods = [
                    n.name for n in classes[0].body if isinstance(n, ast.FunctionDef)
                ]
                self.assertNotIn("infer", methods)
                self.assertNotIn("_infer", methods)
                self.assertTrue(
                    any(
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == call
                        for n in ast.walk(tree)
                    )
                )
                imports = [
                    n.module or ""
                    for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom)
                ]
                self.assertFalse(
                    any(
                        x.startswith(("serving", "scripts", "qwen_node", "yolo_node"))
                        for x in imports
                    )
                )
                self.assertNotIn("workload_mode", self.source(kind))

    def test_callbacks_only_enqueue_original_messages_in_fifo_order(self):
        for kind in ["qwen", "yolo"]:
            node = self.fake_node()
            callback = self.callback(kind)
            messages = [object(), object(), object()]
            for message in messages:
                callback(node, message)
            items = [node.requests.get_nowait() for _ in messages]
            self.assertEqual([i[0] for i in items], [1, 2, 3])
            self.assertEqual([i[2] for i in items], messages)
            self.assertTrue(all(i[1] > 0 for i in items))
            # object() has no text/image attributes: callback cannot parse or infer.

    def test_queue_full_does_not_block_callback_or_replace_oldest(self):
        for kind in ["qwen", "yolo"]:
            node = self.fake_node(capacity=1)
            callback = self.callback(kind)
            first, second = object(), object()
            callback(node, first)
            started = time.perf_counter()
            callback(node, second)
            self.assertLess(time.perf_counter() - started, 0.1)
            self.assertIs(node.requests.get_nowait()[2], first)
            node.logger.warning.assert_called_once()

    def test_two_nodes_have_independent_request_queues(self):
        qwen, yolo = self.fake_node(), self.fake_node()
        self.callback("qwen")(qwen, object())
        self.assertEqual(qwen.requests.qsize(), 1)
        self.assertEqual(yolo.requests.qsize(), 0)
        self.callback("yolo")(yolo, object())
        self.assertEqual(yolo.requests.qsize(), 1)
        self.assertIsNot(qwen.requests, yolo.requests)

    def test_fifo_worker_and_no_cross_model_dependency(self):
        for kind, other in [("qwen", "yolo"), ("yolo", "qwen")]:
            source = self.source(kind)
            self.assertIn("requests.get(", source)
            self.assertNotIn(other, source.lower())
            self.assertNotIn("LifoQueue", source)
            self.assertNotIn("deque(maxlen", source)
