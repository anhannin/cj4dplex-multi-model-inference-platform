"""Persistent QwenC1; finish current request when asked to stop; never hide errors."""

import argparse
import json
import time
from pathlib import Path
from ros_client import RosClient, atomic

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
root = a.root
work = json.loads((root / "workload.json").read_text())
client = RosClient("qwen")
state = {"state": "RUNNING", "warmup": 0, "measured": 0, "errors": []}
file = root / "verification/qwen-monitor-status.json"
atomic(file, state)
try:
    client.wait_subscriber()
    with (root / "results/qwen-requests.jsonl").open("x") as out:
        index = 0
        while not (root / "control/stop-qwen").exists():
            rid = client.prepare(
                "idle-fault-qwen",
                {"text": work["text"], "max_new_tokens": 128, "timing_mode": "tokens"},
            )
            client.send()
            atomic(
                root / "control/qwen-inflight.json",
                {
                    "request_id": rid,
                    "sent_ns": client.sent_ns,
                    "state": "waiting",
                    "index": index,
                },
            )
            row = client.wait_result(75)
            row.update(index=index, warmup=index < 3)
            assert row["response"]["input_ids_sha256"] == work["input_ids_sha256"]
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            atomic(
                root / "control/qwen-inflight.json",
                {
                    "request_id": rid,
                    "sent_ns": client.sent_ns,
                    "received_ns": row["received_ns"],
                    "state": "complete",
                    "index": index,
                },
            )
            state["warmup" if row["warmup"] else "measured"] += 1
            atomic(file, state)
            client.release(0.15)
            index += 1
    state["state"] = "PASS"
except BaseException as e:
    state.update(state="FAIL")
    state["errors"].append(repr(e))
    raise
finally:
    client.close()
    state["end_ns"] = time.perf_counter_ns()
    atomic(file, state)
