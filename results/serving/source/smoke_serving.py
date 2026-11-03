"""Real HTTP functional smoke test; not a performance/SLO benchmark."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid


def post(url, body, content_type, timeout=180):
    request = Request(
        url, data=body, headers={"Content-Type": content_type}, method="POST"
    )
    started = time.perf_counter()
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    return {"http_e2e_ms": (time.perf_counter() - started) * 1000, "response": result}


def generate(text, tokens=32, timeout=180):
    return post(
        "http://127.0.0.1:8001/generate",
        json.dumps({"text": text, "max_new_tokens": tokens}).encode(),
        "application/json",
        timeout,
    )


def detect(path):
    boundary = uuid.uuid4().hex
    data = path.read_bytes()
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="image.jpg"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return post(
        "http://127.0.0.1:8002/detect",
        body,
        "multipart/form-data; boundary=" + boundary,
    )


def logs(kind):
    return subprocess.check_output(
        ["docker", "logs", "cj-" + kind + "-api"], text=True, stderr=subprocess.STDOUT
    )


def events(kind):
    result = []
    for line in logs(kind).splitlines():
        if line.startswith("{"):
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--assets", type=Path, default=Path.home() / "cj-containers/assets"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = {
        "state": "running",
        "scope": "functional smoke; not SLO evidence",
        "cases": {},
    }

    def save():
        (args.output / "summary.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )

    try:
        deadline = time.monotonic() + 600
        for kind, port in [("qwen", 8001), ("yolo", 8002)]:
            while True:
                state = subprocess.check_output(
                    [
                        "docker",
                        "inspect",
                        "-f",
                        "{{.State.Running}}",
                        "cj-" + kind + "-api",
                    ],
                    text=True,
                ).strip()
                if state != "true":
                    raise RuntimeError(kind + " container exited during startup")
                try:
                    with urlopen(
                        f"http://127.0.0.1:{port}/openapi.json", timeout=2
                    ) as response:
                        assert response.status == 200
                    with urlopen(
                        f"http://127.0.0.1:{port}/docs", timeout=2
                    ) as response:
                        assert response.status == 200
                    break
                except (URLError, ConnectionError, TimeoutError):
                    if time.monotonic() > deadline:
                        raise TimeoutError("Model startup timed out")
                    time.sleep(2)
        images = [args.assets / "bus.jpg", args.assets / "zidane.jpg"]
        result["inputs_sha256"] = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in images
        }
        cases = result["cases"]
        cases["qwen_one"] = generate(
            "Summarize in one sentence: Two AI models share one GPU and receive independent requests."
        )
        cases["qwen_two"] = generate(
            "List two benefits of keeping an AI model resident in GPU memory."
        )
        for name, path in zip(["yolo_one", "yolo_two"], images):
            cases[name] = detect(path)
        previous = max(
            e["sequence"]
            for e in events("qwen")
            if e.get("event") == "inference_started"
        )
        with ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(
                generate,
                "Explain GPU resource contention in detail using at least six bullet points.",
                128,
            )
            deadline = time.monotonic() + 10
            while not any(
                e.get("event") == "inference_started"
                and e.get("sequence") == previous + 1
                for e in events("qwen")
            ):
                if time.monotonic() > deadline:
                    raise TimeoutError("Qwen did not start")
                time.sleep(0.02)
            try:
                generate(
                    "This waiting request should be abandoned before inference.",
                    32,
                    timeout=0.3,
                )
                raise AssertionError("Expected queued client timeout")
            except (TimeoutError, socket.timeout):
                result["queued_client_timeout"] = "expected"
            second = pool.submit(
                generate,
                "Explain three ways to measure AI serving latency and throughput.",
                64,
            )
            cv_one = pool.submit(detect, images[0])
            cv_two = pool.submit(detect, images[1])
            cases["parallel_yolo_one"] = cv_one.result(timeout=60)
            cases["parallel_yolo_two"] = cv_two.result(timeout=60)
            cases["parallel_qwen_first"] = first.result(timeout=180)
            cases["parallel_qwen_second"] = second.result(timeout=180)
        for name, case in cases.items():
            body = case["response"]
            assert body["processing_ms"] > 0 and body["queue_wait_ms"] >= 0
            assert case["http_e2e_ms"] > 0
            if "qwen" in name:
                assert body["text"].strip() and 0 < body["output_tokens"] <= 128
            else:
                assert body["width"] > 0 and body["height"] > 0 and body["detections"]
                for detection in body["detections"]:
                    assert 0 <= detection["confidence"] <= 1
                    x1, y1, x2, y2 = detection["xyxy"]
                    assert (
                        0 <= x1 <= x2 <= body["width"]
                        and 0 <= y1 <= y2 <= body["height"]
                    )
        qevents = events("qwen")
        assert not any(
            e.get("event") == "inference_started" and e.get("sequence") == previous + 2
            for e in qevents
        ), "Abandoned queued request executed"
        assert cases["parallel_qwen_second"]["response"]["queue_wait_ms"] > 100
        intervals = {}
        for kind in ["qwen", "yolo"]:
            entries = events(kind)
            assert sum(e.get("event") == "backend_loaded" for e in entries) == 1
            assert sum(e.get("event") == "model_ready" for e in entries) == 1
            starts = {
                e["request_id"]: e
                for e in entries
                if e.get("event") == "inference_started"
            }
            finishes = {
                e["request_id"]: e
                for e in entries
                if e.get("event") == "inference_finished"
            }
            completed = sorted(
                [
                    (e["sequence"], e["time"], finishes[rid]["time"])
                    for rid, e in starts.items()
                ]
            )
            assert all(a[2] <= b[1] for a, b in zip(completed, completed[1:])), (
                "Same-model inference overlapped"
            )
            for rid, start in starts.items():
                intervals[rid] = [start["time"], finishes[rid]["time"]]
        qid = cases["parallel_qwen_first"]["response"]["request_id"]
        yid = cases["parallel_yolo_one"]["response"]["request_id"]
        assert (
            intervals[qid][0]
            < intervals[yid][0]
            < intervals[yid][1]
            < intervals[qid][1]
        ), "YOLO blocked by Qwen"
        result["intervals_unix_seconds"] = intervals
        result["queued_request_skipped"] = True
        result["same_model_serialized"] = True
        result["cross_model_processing_overlap"] = True
        # Expected invalid-input requests are separate from valid inference successes.
        for label, url, body, content_type, status in [
            (
                "empty_text",
                "http://127.0.0.1:8001/generate",
                b'{"text":""}',
                "application/json",
                422,
            ),
            (
                "invalid_image",
                "http://127.0.0.1:8002/detect",
                b"{}",
                "application/json",
                422,
            ),
        ]:
            try:
                post(url, body, content_type)
                raise AssertionError("Invalid request was accepted")
            except HTTPError as error:
                assert error.code == status
                result[label + "_status"] = status
        result["state"] = "PASS"
    except Exception as error:
        result["state"] = "FAIL"
        result["error"] = repr(error)
        raise
    finally:
        save()
        for kind in ["qwen", "yolo"]:
            (args.output / (kind + ".log")).write_text(logs(kind))
    print(
        json.dumps(
            {
                "state": result["state"],
                "output": str(args.output),
                "successful_requests": len(result["cases"]),
            }
        )
    )


if __name__ == "__main__":
    main()
