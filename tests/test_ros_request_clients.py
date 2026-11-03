import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def client(kind):
    spec = importlib.util.spec_from_file_location(
        "ros_client_" + kind, ROOT / "clients" / f"request_{kind}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RequestClientTests(unittest.TestCase):
    def test_only_own_request_id_is_accepted(self):
        rid = "r_" + "a" * 32
        for kind in ["qwen", "yolo"]:
            module = client(kind)
            self.assertIsNone(
                module.parse_result(json.dumps({"request_id": "r_" + "b" * 32}), rid)
            )
            self.assertIsNone(module.parse_result("bad json", rid))
            self.assertIsNone(module.parse_result("[]", rid))
            self.assertEqual(
                module.parse_result(
                    json.dumps({"request_id": rid, "status": "ok"}), rid
                )["status"],
                "ok",
            )

    def test_image_is_annotated_without_overwriting_input(self):
        module = client("yolo")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.png"
            out = Path(folder) / "result.png"
            Image.new("RGB", (100, 80), "white").save(source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            reply = {
                "request_id": "r_" + "c" * 32,
                "width": 100,
                "height": 80,
                "detections": [
                    {
                        "class_id": 0,
                        "label": "test",
                        "confidence": 0.9,
                        "xyxy": [10, 10, 60, 60],
                    }
                ],
            }
            self.assertEqual(module.save_result_image(source, out, reply), out)
            self.assertTrue(out.exists())
            with Image.open(out) as image:
                self.assertNotEqual(image.getpixel((10, 10)), (255, 255, 255))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            with self.assertRaises(FileExistsError):
                module.save_result_image(source, out, reply)
            with self.assertRaises(FileExistsError):
                module.save_result_image(source, source, reply)
