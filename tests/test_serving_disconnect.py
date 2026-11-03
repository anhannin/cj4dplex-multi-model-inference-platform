"""Real TCP regression: a timed-out queued HTTP request must not run later."""

import http.client
import json
import socket
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
import uvicorn
from serving.qwen_app import create_app


class DisconnectTests(unittest.TestCase):
    def test_disconnected_waiting_client_is_skipped_over_real_http(self):
        started, release = threading.Event(), threading.Event()
        seen = []

        def infer(payload):
            seen.append(payload["text"])
            if payload["text"] == "first":
                started.set()
                release.wait(5)
            return {"text": payload["text"], "output_tokens": 1}

        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(lambda: infer), log_level="warning", access_log=False
            )
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
            req = Request(
                f"http://127.0.0.1:{port}/generate",
                data=json.dumps({"text": text}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=5) as response:
                return json.load(response)

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(request, "first")
                self.assertTrue(started.wait(2))
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.2)
                try:
                    connection.request(
                        "POST",
                        "/generate",
                        json.dumps({"text": "abandoned"}),
                        {"Content-Type": "application/json"},
                    )
                    with self.assertRaises(TimeoutError):
                        connection.getresponse()
                finally:
                    connection.close()
                time.sleep(0.4)
                release.set()
                self.assertEqual(first.result()["text"], "first")
                self.assertEqual(request("last")["text"], "last")
            self.assertEqual(seen, ["first", "last"])
        finally:
            release.set()
            server.should_exit = True
            thread.join(3)
            sock.close()
            self.assertFalse(thread.is_alive())
