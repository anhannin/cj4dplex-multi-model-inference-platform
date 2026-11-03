"""Standalone API contracts with mocked SDKs; GPU/real HTTP validation is separate."""

import ast
from contextlib import nullcontext
import importlib.util
import io
from pathlib import Path
import threading
import types
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import time
from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load(kind):
    path = ROOT / "api" / (kind + "_api.py")
    spec = importlib.util.spec_from_file_location("standalone_" + kind, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SDKs:
    def __init__(self):
        self.loads = 0
        self.calls = []
        self.threads = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        owner = self
        torch = types.ModuleType("torch")
        torch.bfloat16, torch.float16 = "bf16", "fp16"
        torch.set_num_threads = lambda value: None
        torch.cuda = types.SimpleNamespace(
            set_device=lambda v: None, synchronize=lambda: None
        )
        torch.inference_mode = nullcontext

        class Tensor:
            def __init__(self, text):
                self.text = text
                self.shape = (1, 2049 if text == "TOO_LONG" else 4)

            def to(self, device):
                return self

        class Tokenizer:
            eos_token_id = 0

            @classmethod
            def from_pretrained(cls, *a, **kw):
                return cls()

            def apply_chat_template(self, messages, **kw):
                return messages[0]["content"]

            def __call__(self, text, **kw):
                return {"input_ids": Tensor(text)}

            def decode(self, tokens, **kw):
                return tokens.text

        class Output:
            def __init__(self, text):
                self.text = text.upper()
                self.shape = (2,)

            def __getitem__(self, item):
                return self

        class Model:
            @classmethod
            def from_pretrained(cls, *a, **kw):
                owner.loads += 1
                return cls()

            def eval(self):
                return self

            def to(self, device):
                return self

            def generate(self, **kw):
                text = kw["input_ids"].text
                owner.calls.append(text)
                owner.threads.append(threading.get_ident())
                if text == "hold":
                    owner.started.set()
                    owner.release.wait(5)
                if text == "error":
                    raise RuntimeError("private internal error")
                return Output(text)

        transformers = types.ModuleType("transformers")
        transformers.AutoTokenizer = Tokenizer
        transformers.Qwen3_5ForConditionalGeneration = Model
        implementation = types.ModuleType(
            "transformers.models.qwen3_5.modeling_qwen3_5"
        )

        def wrapper(implementation):
            def wrapped():
                return implementation()

            return wrapped

        for name, prefix in [
            ("causal_conv1d_fn", "causal_conv1d."),
            ("causal_conv1d_update", "causal_conv1d."),
            ("torch_chunk_gated_delta_rule", "fla."),
            ("torch_recurrent_gated_delta_rule", "fla."),
        ]:

            def selected():
                pass

            selected.__module__ = prefix + "test"
            setattr(implementation, name, wrapper(selected))
        qwen = types.ModuleType("transformers.models.qwen3_5")
        qwen.modeling_qwen3_5 = implementation

        class Yolo:
            def __init__(self, *a, **kw):
                owner.loads += 1
                self.predictor = types.SimpleNamespace(
                    model=types.SimpleNamespace(
                        device=types.SimpleNamespace(type="cuda"),
                        fp16=True,
                        model=types.SimpleNamespace(
                            parameters=lambda: iter(
                                [
                                    types.SimpleNamespace(
                                        dtype="fp16",
                                        device=types.SimpleNamespace(type="cuda"),
                                    )
                                ]
                            )
                        ),
                    )
                )

            def predict(self, image, **kw):
                if image.size != (640, 640):
                    owner.calls.append(image.size)
                    owner.threads.append(threading.get_ident())
                values = types.SimpleNamespace(
                    cpu=lambda: types.SimpleNamespace(
                        tolist=lambda: [[1, 2, 10, 12, 0.9, 0]]
                    )
                )
                return [
                    types.SimpleNamespace(
                        boxes=types.SimpleNamespace(data=values), names={0: "test"}
                    )
                ]

        ultralytics = types.ModuleType("ultralytics")
        ultralytics.YOLO = Yolo
        self.modules = {
            "torch": torch,
            "transformers": transformers,
            "transformers.models": types.ModuleType("transformers.models"),
            "transformers.models.qwen3_5": qwen,
            "transformers.models.qwen3_5.modeling_qwen3_5": implementation,
            "ultralytics": ultralytics,
        }


def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (24, 16)).save(out, "PNG")
    return out.getvalue()


class StandaloneTests(unittest.TestCase):
    def test_files_have_direct_native_calls_and_no_project_imports(self):
        for kind, call in [("qwen", "generate"), ("yolo", "predict")]:
            source = (ROOT / "api" / (kind + "_api.py")).read_text()
            tree = ast.parse(source)
            imports = [
                n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
            ]
            self.assertFalse(
                any(
                    n.startswith(("serving", "scripts", "qwen_api", "yolo_api"))
                    for n in imports
                )
            )
            self.assertFalse(
                any(
                    isinstance(n, ast.ClassDef) and "backend" in n.name.lower()
                    for n in ast.walk(tree)
                )
            )
            self.assertTrue(
                any(
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == call
                    for n in ast.walk(tree)
                )
            )
            self.assertIn("if __name__", source)

    def test_qwen_load_once_responses_and_limits(self):
        sdk = SDKs()
        with patch.dict("sys.modules", sdk.modules):
            module = load("qwen")
            with TestClient(module.create_app()) as client:
                for text in ["hello", "world"]:
                    response = client.post(
                        "/generate", json={"text": text, "max_new_tokens": 8}
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()["text"], text.upper())
                    self.assertIn("queue_wait_ms", response.json())
                self.assertEqual(client.get("/docs").status_code, 200)
                for data in [{}, {"text": ""}, {"text": "a", "max_new_tokens": 513}]:
                    self.assertEqual(
                        client.post("/generate", json=data).status_code, 422
                    )
                self.assertEqual(
                    client.post("/generate", json={"text": "TOO_LONG"}).status_code, 422
                )
                self.assertEqual(
                    client.post("/generate", json={"text": "error"}).status_code, 500
                )
                self.assertEqual(
                    client.post("/generate", json={"text": "after"}).status_code, 200
                )
        self.assertEqual(sdk.loads, 1)
        self.assertEqual(len(set(sdk.threads)), 1)
        self.assertNotIn("TOO_LONG", sdk.calls)

    def test_yolo_image_and_invalid_input(self):
        sdk = SDKs()
        with patch.dict("sys.modules", sdk.modules):
            module = load("yolo")
            with TestClient(module.create_app()) as client:
                response = client.post(
                    "/detect", files={"file": ("x.png", image_bytes())}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["width"], 24)
                self.assertEqual(response.json()["detections"][0]["label"], "test")
                self.assertEqual(
                    client.post("/detect", files={"file": ("bad", b"no")}).status_code,
                    400,
                )
                self.assertEqual(
                    client.post(
                        "/detect",
                        files={"file": ("big", b"x" * (10 * 1024 * 1024 + 1))},
                    ).status_code,
                    413,
                )
                self.assertEqual(client.get("/docs").status_code, 200)
        self.assertEqual(sdk.loads, 1)
        self.assertEqual(sdk.calls, [(24, 16)])

    def test_fifo_full_and_other_model_independence(self):
        sdk = SDKs()
        sdk.release.clear()
        with patch.dict("sys.modules", sdk.modules):
            q = load("qwen").create_app(queue_capacity=1)
            y = load("yolo").create_app()
            with (
                TestClient(q) as qc,
                TestClient(y) as yc,
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                first = pool.submit(qc.post, "/generate", json={"text": "hold"})
                self.assertTrue(sdk.started.wait(2))
                second = pool.submit(qc.post, "/generate", json={"text": "second"})
                try:
                    deadline = time.monotonic() + 2
                    while q.state.requests.qsize() != 1 and time.monotonic() < deadline:
                        time.sleep(0.005)
                    self.assertEqual(q.state.requests.qsize(), 1)
                    self.assertEqual(
                        qc.post("/generate", json={"text": "third"}).status_code, 429
                    )
                    self.assertFalse(second.done())
                    self.assertEqual(
                        yc.post(
                            "/detect", files={"file": ("x.png", image_bytes())}
                        ).status_code,
                        200,
                    )
                    self.assertFalse(first.done())
                finally:
                    sdk.release.set()
                self.assertEqual(first.result().json()["text"], "HOLD")
                self.assertEqual(second.result().json()["text"], "SECOND")
                self.assertGreater(second.result().json()["queue_wait_ms"], 0)
        self.assertEqual(
            [c for c in sdk.calls if isinstance(c, str)], ["hold", "second"]
        )

    def test_disconnected_waiter_is_skipped_over_real_tcp(self):
        import http.client
        import socket
        from urllib.request import Request, urlopen
        import uvicorn

        sdk = SDKs()
        sdk.release.clear()
        with patch.dict("sys.modules", sdk.modules):
            app = load("qwen").create_app()
            sock = socket.socket()
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(
                uvicorn.Config(app, access_log=False, log_level="warning")
            )
            thread = threading.Thread(
                target=server.run, kwargs={"sockets": [sock]}, daemon=True
            )
            thread.start()
            deadline = time.monotonic() + 3
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(server.started)

            def request(text):
                import json

                body = json.dumps({"text": text}).encode()
                with urlopen(
                    Request(
                        f"http://127.0.0.1:{port}/generate",
                        data=body,
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=5,
                ) as response:
                    return json.load(response)

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(request, "hold")
                    self.assertTrue(sdk.started.wait(2))
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", port, timeout=0.2
                    )
                    try:
                        connection.request(
                            "POST",
                            "/generate",
                            '{"text":"abandoned"}',
                            {"Content-Type": "application/json"},
                        )
                        with self.assertRaises(TimeoutError):
                            connection.getresponse()
                    finally:
                        connection.close()
                    time.sleep(0.4)
                    sdk.release.set()
                    self.assertEqual(pending.result()["text"], "HOLD")
                    self.assertEqual(request("after")["text"], "AFTER")
                self.assertEqual(sdk.calls, ["hold", "after"])
            finally:
                sdk.release.set()
                server.should_exit = True
                thread.join(3)
                sock.close()
                self.assertFalse(thread.is_alive())
