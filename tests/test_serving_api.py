import io
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from PIL import Image
from fastapi.testclient import TestClient
from serving.qwen_app import create_app as qwen_app
from serving.yolo_app import create_app as yolo_app
from serving.backends import decode_image, prepare_qwen_inputs, InputError


def image_bytes(fmt="PNG"):
    out = io.BytesIO()
    Image.new("RGB", (24, 16), "white").save(out, format=fmt)
    return out.getvalue()


class APITests(unittest.TestCase):
    def test_qwen_responses_and_single_model_load(self):
        loads = []

        def factory():
            loads.append(1)
            return lambda p: {"text": p["text"].upper(), "output_tokens": 2}

        with TestClient(qwen_app(factory)) as client:
            for text in ["hello", "world"]:
                response = client.post(
                    "/generate", json={"text": text, "max_new_tokens": 8}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["text"], text.upper())
                self.assertIn("queue_wait_ms", response.json())
                self.assertIn("request_id", response.json())
            self.assertEqual(client.get("/docs").status_code, 200)
            self.assertIn("/generate", client.get("/openapi.json").json()["paths"])
        self.assertEqual(loads, [1])

    def test_invalid_qwen_requests_do_not_invoke_model(self):
        calls = []
        with TestClient(qwen_app(lambda: lambda p: calls.append(p))) as client:
            for payload in [
                {},
                {"text": ""},
                {"text": "   "},
                {"text": "a", "max_new_tokens": 0},
                {"text": "a", "max_new_tokens": 513},
                {"text": "a" * 32769},
            ]:
                self.assertEqual(
                    client.post("/generate", json=payload).status_code, 422
                )
        self.assertEqual(calls, [])

    def test_yolo_file_response(self):
        def infer(image):
            return {
                "width": image.width,
                "height": image.height,
                "detections": [
                    {
                        "class_id": 0,
                        "label": "test",
                        "confidence": 0.9,
                        "xyxy": [1, 2, 10, 12],
                    }
                ],
            }

        with TestClient(yolo_app(lambda: infer)) as client:
            for fmt in ["PNG", "JPEG"]:
                response = client.post(
                    "/detect", files={"file": ("image", image_bytes(fmt))}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["width"], 24)
                self.assertEqual(response.json()["height"], 16)
                self.assertEqual(response.json()["detections"][0]["class_id"], 0)
            self.assertEqual(client.get("/docs").status_code, 200)

    def test_invalid_yolo_files_do_not_invoke_model(self):
        calls = []
        with TestClient(yolo_app(lambda: lambda p: calls.append(p))) as client:
            self.assertEqual(client.post("/detect").status_code, 422)
            for data in [b"not an image", image_bytes("GIF")]:
                self.assertEqual(
                    client.post("/detect", files={"file": ("bad", data)}).status_code,
                    400,
                )
            self.assertEqual(
                client.post(
                    "/detect", files={"file": ("large", b"x" * (10 * 1024 * 1024 + 1))}
                ).status_code,
                413,
            )
        self.assertEqual(calls, [])

    def test_backend_input_error_and_unexpected_error(self):
        def infer(payload):
            if payload["text"] == "long":
                raise InputError(422, "Input exceeds token limit")
            raise RuntimeError("internal detail must not leak")

        with TestClient(qwen_app(lambda: infer)) as client:
            self.assertEqual(
                client.post("/generate", json={"text": "long"}).status_code, 422
            )
            response = client.post("/generate", json={"text": "fail"})
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("internal detail", response.text)

    def test_yolo_can_finish_while_qwen_running(self):
        started, release = threading.Event(), threading.Event()

        def infer(payload):
            started.set()
            release.wait(5)
            return {"text": "done", "output_tokens": 1}

        with (
            TestClient(qwen_app(lambda: infer)) as qwen,
            TestClient(
                yolo_app(
                    lambda: lambda image: {
                        "width": image.width,
                        "height": image.height,
                        "detections": [],
                    }
                )
            ) as yolo,
        ):
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(qwen.post, "/generate", json={"text": "wait"})
                self.assertTrue(started.wait(2))
                try:
                    reply = yolo.post(
                        "/detect", files={"file": ("test.png", image_bytes())}
                    )
                    self.assertEqual(reply.status_code, 200)
                    self.assertFalse(pending.done())
                finally:
                    release.set()
                self.assertEqual(pending.result().status_code, 200)

    def test_token_limit_includes_chat_template(self):
        class Tokenizer:
            def apply_chat_template(self, *args, **kwargs):
                return "template"

            def __call__(self, *args, **kwargs):
                return {"input_ids": SimpleNamespace(shape=(1, 2049))}

        with self.assertRaises(InputError):
            prepare_qwen_inputs(Tokenizer(), "test")

    def test_decoded_image_pixel_limit(self):
        from unittest.mock import patch

        fake = SimpleNamespace(format="PNG", width=5000, height=4000)
        context = unittest.mock.MagicMock()
        context.__enter__.return_value = fake
        with patch("serving.backends.Image.open", return_value=context):
            with self.assertRaises(InputError) as error:
                decode_image(b"header")
            self.assertEqual(error.exception.status_code, 413)


class LoggingTests(unittest.TestCase):
    def test_serving_logger_records_inference_events_without_prompt(self):
        import logging

        self.assertEqual(logging.getLogger("serving").getEffectiveLevel(), logging.INFO)
        with self.assertLogs("serving", level="INFO") as captured:
            with TestClient(
                qwen_app(lambda: lambda p: {"text": "result", "output_tokens": 1})
            ) as client:
                client.post("/generate", json={"text": "PRIVATE_PROMPT_DO_NOT_LOG"})
        messages = "\n".join(record.getMessage() for record in captured.records)
        self.assertIn("inference_started", messages)
        self.assertIn("inference_finished", messages)
        self.assertNotIn("PRIVATE_PROMPT_DO_NOT_LOG", messages)


class AdmissionTests(unittest.TestCase):
    def test_same_model_waits_and_only_full_queue_returns_429(self):
        import time

        started, release = threading.Event(), threading.Event()

        def infer(payload):
            if payload["text"] == "first":
                started.set()
                release.wait(5)
            return {"text": payload["text"], "output_tokens": 1}

        app = qwen_app(lambda: infer, queue_capacity=1)
        with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(client.post, "/generate", json={"text": "first"})
            self.assertTrue(started.wait(2))
            second = executor.submit(client.post, "/generate", json={"text": "second"})
            deadline = time.monotonic() + 2
            try:
                while (
                    app.state.queue.waiting_count != 1 and time.monotonic() < deadline
                ):
                    time.sleep(0.005)
                self.assertEqual(app.state.queue.waiting_count, 1)
                self.assertFalse(second.done())
                self.assertEqual(client.get("/docs").status_code, 200)
                self.assertEqual(
                    client.post("/generate", json={"text": "third"}).status_code, 429
                )
            finally:
                release.set()
            self.assertEqual(first.result().json()["text"], "first")
            self.assertEqual(second.result().json()["text"], "second")
