import ast
import json
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]


class UUIDChannelTests(unittest.TestCase):
    def method(self, kind):
        tree = ast.parse((ROOT / "ros2" / f"{kind}_node.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        method = next(
            n
            for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "_publish_result"
        )
        ns = {
            "re": re,
            "json": json,
            "time": time,
            "rclpy": SimpleNamespace(ok=lambda **kw: True),
            "String": lambda **kw: SimpleNamespace(**kw),
            "Duration": lambda **kw: kw,
        }
        exec(
            compile(
                ast.Module(body=[method], type_ignores=[]), "<reply-method>", "exec"
            ),
            ns,
        )
        return ns["_publish_result"]

    def fake(self, counts=None):
        pub = Mock()
        pub.wait_for_all_acked.return_value = True
        pub.get_subscription_count.side_effect = counts or [1]
        logger = Mock()
        node = SimpleNamespace(
            create_publisher=Mock(return_value=pub),
            destroy_publisher=Mock(),
            stopping=threading.Event(),
            context=None,
            result_timeout=0.02,
            get_logger=lambda: logger,
        )
        return node, pub

    def test_exact_request_channel_and_cleanup_after_ack(self):
        for kind in ["qwen", "yolo"]:
            method = self.method(kind)
            node, pub = self.fake([0, 1])
            rid = "r_" + "a" * 32
            payload = {"request_id": rid, "status": "ok"}
            self.assertTrue(method(node, rid, payload))
            self.assertEqual(
                node.create_publisher.call_args.args[1], f"/{kind}/result/{rid}"
            )
            self.assertEqual(json.loads(pub.publish.call_args.args[0].data), payload)
            pub.wait_for_all_acked.assert_called_once()
            node.destroy_publisher.assert_called_once_with(pub)

    def test_invalid_ids_cannot_create_arbitrary_topics(self):
        for kind in ["qwen", "yolo"]:
            method = self.method(kind)
            for bad in [
                "",
                "abc001",
                "r_" + "1" * 31,
                "r_" + "a" * 32 + "/extra",
                None,
            ]:
                node, pub = self.fake()
                self.assertFalse(method(node, bad, {}))
                node.create_publisher.assert_not_called()
                pub.publish.assert_not_called()

    def test_missing_subscriber_times_out_and_cleans_publisher(self):
        for kind in ["qwen", "yolo"]:
            method = self.method(kind)
            node, pub = self.fake()
            pub.get_subscription_count.side_effect = None
            pub.get_subscription_count.return_value = 0
            self.assertFalse(method(node, "r_" + "b" * 32, {}))
            pub.publish.assert_not_called()
            node.destroy_publisher.assert_called_once_with(pub)

    def test_request_types_are_fixed_strings_and_no_broadcast_results(self):
        for kind in ["qwen", "yolo"]:
            source = (ROOT / "ros2" / f"{kind}_node.py").read_text()
            self.assertNotIn("CompressedImage", source)
            self.assertNotIn("self.results =", source)
            self.assertIn("self._publish_result(", source)

    def test_requests_are_retained_until_late_model_reader_matches(self):
        for kind in ["qwen", "yolo"]:
            for path in [
                ROOT / "ros2" / f"{kind}_node.py",
                ROOT / "clients" / f"request_{kind}.py",
            ]:
                self.assertIn(
                    "DurabilityPolicy.TRANSIENT_LOCAL", path.read_text(), str(path)
                )
