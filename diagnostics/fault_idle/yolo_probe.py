"""One patient recovery request, published exactly once AFTER the fault marker."""

import argparse
import base64
import time
from pathlib import Path
from ros_client import RosClient, atomic

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
p.add_argument("--trial", required=True)
p.add_argument("--wait-fault", action="store_true")
a = p.parse_args()
root = a.root
folder = root / "results" / a.trial
folder.mkdir(exist_ok=True)
image = base64.b64encode(
    (Path.home() / "cj-containers/assets/bus.jpg").read_bytes()
).decode("ascii")
client = RosClient("yolo")
result = {
    "state": "RUNNING",
    "application_retries": 0,
    "patient_timeout_s": 90,
    "transport": "reliabletransientlocaldepth1,publisherkeptalive",
}
try:
    rid = client.prepare(a.trial, {"image_base64": image})
    client.wait_subscriber(90)
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        client.spin(0.01)
    atomic(
        folder / "probe-ready.json",
        {"request_id": rid, "ready_ns": time.perf_counter_ns()},
    )
    if a.wait_fault:
        deadline = time.monotonic() + 90
        while not (folder / "fault.json").exists():
            if time.monotonic() > deadline:
                raise TimeoutError("No fault trigger")
            client.spin(0.01)
    client.send()
    atomic(
        folder / "probe-sent.json",
        {
            "request_id": rid,
            "sent_ns": client.sent_ns,
            "matches_at_publish": client.matches_at_send,
            "publish_count": 1,
        },
    )
    row = client.wait_result(90)
    assert len(row["response"]["detections"]) == 5
    result.update(state="PASS", **row)
    atomic(folder / "probe-result.json", result)
    client.release(1)
except BaseException as e:
    result.update(state="FAIL", error=repr(e))
    atomic(folder / "probe-result.json", result)
    raise
finally:
    client.close()
