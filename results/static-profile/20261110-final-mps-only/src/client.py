#!/usr/bin/env python3
"""Finite simultaneous Q/Y burst; never wait for a result before sending remaining jobs."""

import argparse
import base64
import json
import os
from pathlib import Path
import threading
import time
import uuid

from metrics import burst_completion, request_parts


def main():
    import rclpy
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from std_msgs.msg import String

    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--qwen-count", type=int, default=10)
    p.add_argument("--yolo-count", type=int, default=300)
    p.add_argument("--qwen-sm", type=int, required=True)
    p.add_argument("--yolo-sm", type=int, required=True)
    p.add_argument("--green", type=int, required=True)
    p.add_argument("--timeout", type=float, default=600)
    p.add_argument("--settle", type=float, default=3)
    a = p.parse_args()
    assert os.environ["ROS_DOMAIN_ID"] == "76"
    assert 1 <= a.qwen_count <= 16 and 1 <= a.yolo_count <= 512
    a.output.mkdir(parents=True, exist_ok=False)
    workload = json.loads((a.root / "workload.json").read_text())
    encoded = base64.b64encode(
        (Path.home() / "cj-containers/assets/bus.jpg").read_bytes()
    ).decode("ascii")
    expected = {"qwen": a.qwen_count, "yolo": a.yolo_count}
    sms = {"qwen": a.qwen_sm, "yolo": a.yolo_sm}
    run_id = a.output.name + "_" + uuid.uuid4().hex[:12]
    rows = {}
    received = {}
    subs = []
    dispatch = {}
    errors = []
    barrier_time = {}
    manifest = {
        "state": "RUNNING",
        "run_id": run_id,
        "expected": expected,
        "sm": sms,
        "green": bool(a.green),
        "workload": {
            k: v for k, v in workload.items() if k not in ("text", "input_ids")
        },
        "ros_domain": 76,
        "load": "finite simultaneous burst, no response-gated pacing",
        "e2e": "before per-request JSON encoding/publish -> matching response parsed",
        "batch_makespan": "common barrier release -> last parsed response",
        "excluded": [
            "initial discovery/subscription preparation",
            "input file/base64 preparation",
        ],
        "start_wall_ns": time.time_ns(),
    }
    rclpy.init(args=[])
    node = rclpy.create_node("burst_" + uuid.uuid4().hex)
    qos = QoSProfile(
        depth=512,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    publishers = {
        m: node.create_publisher(String, "/" + m + "/request", qos) for m in expected
    }
    stream = (a.output / "requests.jsonl").open("x")
    threads = []
    try:

        def on_result(model, rid, message):
            receive = time.perf_counter_ns()
            reply = json.loads(message.data)
            if reply.get("request_id") != rid or reply.get("run_id") != run_id:
                raise RuntimeError("Wrong UUID/batch routing")
            if rid in received:
                raise RuntimeError("Duplicate result")
            entry = rows[rid]
            assert entry["sent_ns"] is not None
            assert reply.get("status") == "ok", reply
            assert reply["assigned_sms"] == sms[model] and reply[
                "green_enabled"
            ] == bool(a.green)
            if model == "qwen":
                assert reply["input_tokens"] == 512 and reply["output_tokens"] == 128
                assert reply["input_ids_sha256"] == workload["input_ids_sha256"]
                assert reply["gpu_forward_lengths"] == [512] + [1] * 127
            else:
                assert reply["gpu_forward_shape"] == [1, 3, 640, 640]
            end = time.perf_counter_ns()
            pipeline_key = "generate_wall_ms" if model == "qwen" else "predict_wall_ms"
            timings = reply["timings_ms"]
            e2e = (end - entry["sent_ns"]) / 1e6
            entry.update(
                status="ok",
                received_ns=end,
                request_e2e_ms=e2e,
                batch_origin_e2e_ms=(end - barrier_time["t0"]) / 1e6,
                response_parse_ms=(end - receive) / 1e6,
                response=reply,
                components=request_parts(
                    e2e,
                    reply["queue_wait_ms"],
                    reply["processing_ms"],
                    timings[pipeline_key],
                    timings["gpu_forward_span_ms"],
                ),
            )
            received[rid] = entry
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            stream.flush()

        for model, count in expected.items():
            for index in range(count):
                rid = "r_" + uuid.uuid4().hex
                rows[rid] = {
                    "request_id": rid,
                    "run_id": run_id,
                    "model": model,
                    "index": index,
                    "sent_ns": None,
                    "status": "pending",
                }
                subs.append(
                    node.create_subscription(
                        String,
                        f"/{model}/result/{rid}",
                        lambda msg, m=model, r=rid: on_result(m, r, msg),
                        QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE),
                    )
                )
        deadline = time.monotonic() + 120
        while any(pub.get_subscription_count() == 0 for pub in publishers.values()):
            if time.monotonic() > deadline:
                raise TimeoutError("Model subscriber not discovered")
            rclpy.spin_once(node, timeout_sec=0.05)
        settle_end = time.monotonic() + a.settle
        while time.monotonic() < settle_end:
            rclpy.spin_once(node, timeout_sec=0.02)
        manifest["setup_complete_wall_ns"] = time.time_ns()
        grouped = {m: [r for r in rows.values() if r["model"] == m] for m in expected}
        def release_barrier():
            barrier_time.update(t0=time.perf_counter_ns(), wall_ns=time.time_ns())
            file=a.root/"control/client-t0.new"
            file.write_text(json.dumps(barrier_time))
            file.replace(a.root/"control/client-t0.json")
        barrier = threading.Barrier(3, action=release_barrier)

        def publish_all(model):
            try:
                barrier.wait(timeout=15)
                for entry in grouped[model]:
                    payload = {"request_id": entry["request_id"], "run_id": run_id}
                    if model == "qwen":
                        payload.update(
                            text=workload["text"],
                            max_new_tokens=128,
                            timing_mode="tokens",
                        )
                    else:
                        payload["image_base64"] = encoded
                    entry["sent_ns"] = time.perf_counter_ns()
                    entry["send_wall_ns"] = time.time_ns()
                    serialized = json.dumps(payload, ensure_ascii=False)
                    publishers[model].publish(String(data=serialized))
                    entry["publish_return_ns"] = time.perf_counter_ns()
                dispatch[model] = {
                    "first_send_ns": grouped[model][0]["sent_ns"],
                    "last_send_ns": grouped[model][-1]["sent_ns"],
                    "last_publish_return_ns": time.perf_counter_ns(),
                }
            except BaseException as error:
                errors.append(repr(error))

        for model in expected:
            thread = threading.Thread(
                target=publish_all,
                args=(model,),
                daemon=True,
                name=model + "-burst-publisher",
            )
            threads.append(thread)
            thread.start()
        barrier.wait(timeout=15)
        deadline = time.monotonic() + a.timeout
        while len(received) < sum(expected.values()):
            if errors:
                raise RuntimeError(errors)
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Missing results: "
                    + str(
                        {
                            m: sum(r["model"] == m for r in received.values())
                            for m in expected
                        }
                    )
                )
            rclpy.spin_once(node, timeout_sec=0.005)
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
        if errors:
            raise RuntimeError(errors)
        summary = burst_completion(
            list(received.values()), barrier_time["t0"], expected
        )
        summary["dispatch"] = {
            m: {
                "first_send_from_t0_ms": (d["first_send_ns"] - barrier_time["t0"])
                / 1e6,
                "last_send_from_t0_ms": (d["last_send_ns"] - barrier_time["t0"]) / 1e6,
                "all_published_from_t0_ms": (
                    d["last_publish_return_ns"] - barrier_time["t0"]
                )
                / 1e6,
            }
            for m, d in dispatch.items()
        }
        summary["dispatch_window_ms"] = (
            max(d["last_publish_return_ns"] for d in dispatch.values())
            - barrier_time["t0"]
        ) / 1e6
        (a.output / "summary.json").write_text(json.dumps(summary, indent=2))
        manifest.update(
            state="PASS",
            batch_t0_perf_ns=barrier_time["t0"],
            batch_t0_wall_ns=barrier_time["wall_ns"],
            completed=len(received),
        )
        # Rewrite canonical final rows once so an early response also retains publish-return metadata.
        (a.output / "final-requests.jsonl").write_text(
            "".join(
                json.dumps(row, ensure_ascii=False) + "\n"
                for row in sorted(
                    received.values(), key=lambda x: (x["model"], x["index"])
                )
            )
        )
        print(json.dumps(summary), flush=True)
    except BaseException as error:
        manifest.update(
            state="FAIL",
            error=repr(error),
            completed=len(received),
            missing_ids=sorted(set(rows) - set(received)),
        )
        raise
    finally:
        manifest["end_wall_ns"] = time.time_ns()
        (a.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        stream.close()
        for sub in subs:
            node.destroy_subscription(sub)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
