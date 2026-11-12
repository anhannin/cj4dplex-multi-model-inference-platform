#!/usr/bin/env python3
"""C1 Qwen plus independently clocked YOLO; bounded rolling UUID readers, full drain."""

import argparse
import base64
import json
import math
import multiprocessing
import os
from pathlib import Path
import threading
import time
import uuid
from protocol import scheduled_offsets, validity, pilot_queue, apply_send_record


def publish_yolo(
    config, ready, start, stop, origin_ns, sent, returned, completed, failures
):
    """Dedicated process: no response-reader churn can hold the publisher's GIL."""
    import rclpy
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from std_msgs.msg import String

    rclpy.init(args=[])
    node = rclpy.create_node("sustained_y_sender_" + uuid.uuid4().hex)
    publisher = node.create_publisher(
        String,
        "/yolo/request",
        QoSProfile(
            depth=512,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        ),
    )
    try:
        deadline = time.monotonic() + 90
        while publisher.get_subscription_count() == 0:
            if time.monotonic() > deadline:
                raise TimeoutError("YOLO publisher discovery")
            rclpy.spin_once(node, timeout_sec=0.02)
        ready.set()
        if not start.wait(90):
            raise TimeoutError("YOLO publisher start barrier")
        for i, offset in enumerate(config["offsets"]):
            scheduled = origin_ns.value + offset
            delay = (scheduled - time.perf_counter_ns()) / 1e9
            if delay > 0:
                stop.wait(delay)
            if stop.is_set():
                return
            payload = {
                "request_id": config["ids"][i],
                "run_id": config["run_id"],
                "image_base64": config["image"],
            }
            sent[i] = time.perf_counter_ns()
            publisher.publish(String(data=json.dumps(payload, ensure_ascii=False)))
            returned[i] = time.perf_counter_ns()
            completed.value = i + 1
        if not publisher.wait_for_all_acked(
            __import__("rclpy.duration", fromlist=["Duration"]).Duration(seconds=5)
        ):
            raise RuntimeError("YOLO request publication ACK timeout")
    except BaseException as error:
        failures.put(repr(error))
        stop.set()
        ready.set()
        raise
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


def main():
    import rclpy
    from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from std_msgs.msg import String

    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--condition", required=True)
    p.add_argument("--round", type=int, default=-1)
    p.add_argument("--phase", default="pilot")
    p.add_argument("--qwen-sm", type=int, required=True)
    p.add_argument("--yolo-sm", type=int, required=True)
    p.add_argument("--drain", type=float, default=300)
    a = p.parse_args()
    assert os.environ["ROS_DOMAIN_ID"] == "74"
    a.output.mkdir(parents=True, exist_ok=False)
    work = json.loads((a.root / "workload.json").read_text())
    image = base64.b64encode(
        (Path.home() / "cj-containers/assets/bus.jpg").read_bytes()
    ).decode("ascii")
    offsets = scheduled_offsets(a.rate, a.duration)
    run_id = a.output.name + "_" + uuid.uuid4().hex
    expected_sm = {"qwen": a.qwen_sm, "yolo": a.yolo_sm}
    entries = {m: [] for m in ("qwen", "yolo")}
    for m, count in [("qwen", math.ceil(a.duration / 2) + 4), ("yolo", len(offsets))]:
        for i in range(count):
            entries[m].append(
                {
                    "model": m,
                    "index": i,
                    "request_id": "r_" + uuid.uuid4().hex,
                    "run_id": run_id,
                    "sent_ns": None,
                    "scheduled_ns": None,
                    "status": "unissued",
                }
            )
    rclpy.init(args=[])
    node = rclpy.create_node("sustained_" + uuid.uuid4().hex)
    qos = QoSProfile(
        depth=512,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )
    pubs = {
        m: node.create_publisher(String, "/" + m + "/request", qos) for m in ("qwen",)
    }
    subscriptions, retire = {}, {}
    q_ready = threading.Event()
    ctx = multiprocessing.get_context("spawn")
    stop = ctx.Event()
    y_ready, y_start = ctx.Event(), ctx.Event()
    y_origin = ctx.Value("q", 0)
    y_sent, y_returned = ctx.Array("q", len(offsets)), ctx.Array("q", len(offsets))
    y_completed = ctx.Value("i", 0)
    y_failures = ctx.Queue()
    errors = []
    origin = {}
    synced_y = 0
    manifest = {
        "state": "RUNNING",
        "phase": a.phase,
        "condition": a.condition,
        "round": a.round,
        "rate": a.rate,
        "duration_s": a.duration,
        "run_id": run_id,
        "ros_domain": 74,
        "qwen_load": "closed-loop C1",
        "yolo_load": "fixed-rate open-loop, dedicated publisher process",
        "result_subscriptions": "rolling 128 ahead; retain >=1s after receive",
        "e2e": "before JSON encoding/publish -> matching result parsed",
        "start_wall_ns": time.time_ns(),
    }
    stream = (a.output / "requests.jsonl").open("x")
    threads = []

    def callback(entry, message):
        try:
            reply = json.loads(message.data)
            if entry["model"] == "yolo" and entry["status"] == "unissued":
                i = entry["index"]
                apply_send_record(
                    entry, y_sent[i], y_returned[i], origin["t0_ns"] + offsets[i]
                )
            if entry["status"] != "pending":
                raise RuntimeError("Duplicate/unissued result " + entry["request_id"])
            assert (
                reply["request_id"] == entry["request_id"] and reply["run_id"] == run_id
            )
            entry.update(response=reply, received_ns=time.perf_counter_ns())
            entry["request_e2e_ms"] = (entry["received_ns"] - entry["sent_ns"]) / 1e6
            entry["scheduled_e2e_ms"] = (
                entry["received_ns"] - entry["scheduled_ns"]
            ) / 1e6
            entry["status"] = reply.get("status", "error")
            if reply.get("status") != "ok":
                errors.append("Server rejected request: " + repr(reply))
            else:
                assert reply["assigned_sms"] == expected_sm[entry["model"]]
                assert reply["green_enabled"] is False
                if entry["model"] == "qwen":
                    assert (
                        reply["input_tokens"] == 512 and reply["output_tokens"] == 128
                    )
                    assert reply["input_ids_sha256"] == work["input_ids_sha256"]
                    assert reply["gpu_forward_lengths"] == [512] + [1] * 127
                else:
                    assert reply["gpu_forward_shape"] == [1, 3, 640, 640]
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            stream.flush()
            retire[entry["request_id"]] = time.monotonic() + 1
            if entry["model"] == "qwen":
                q_ready.set()
        except BaseException as error:
            errors.append(repr(error))
            entry["status"] = "error"
            stop.set()
            q_ready.set()

    def prepare(entry):
        rid = entry["request_id"]
        subscriptions[rid] = node.create_subscription(
            String,
            "/" + entry["model"] + "/result/" + rid,
            lambda msg, e=entry: callback(e, msg),
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE),
        )

    def publish(entry, scheduled):
        if entry["request_id"] not in subscriptions:
            raise RuntimeError(
                "Generator rolling subscription preparation missed schedule"
            )
        payload = {"request_id": entry["request_id"], "run_id": run_id}
        if entry["model"] == "qwen":
            payload.update(text=work["text"], max_new_tokens=128, timing_mode="tokens")
        else:
            payload["image_base64"] = image
        entry.update(
            scheduled_ns=scheduled, sent_ns=time.perf_counter_ns(), status="pending"
        )
        pubs[entry["model"]].publish(
            String(data=json.dumps(payload, ensure_ascii=False))
        )
        entry["publish_return_ns"] = time.perf_counter_ns()

    def q_sender():
        try:
            barrier.wait(timeout=10)
            stop.wait(max(0, (origin["t0_ns"] - time.perf_counter_ns()) / 1e9))
            for entry in entries["qwen"]:
                if stop.is_set() or time.perf_counter_ns() >= origin["stop_ns"]:
                    return
                q_ready.clear()
                publish(entry, time.perf_counter_ns())
                while not q_ready.wait(0.1):
                    if stop.is_set():
                        return
            if time.perf_counter_ns() < origin["stop_ns"]:
                raise RuntimeError("Qwen subscription preallocation exhausted")
        except BaseException as error:
            errors.append(repr(error))
            stop.set()
            q_ready.set()

    def release_barrier():
        now = time.perf_counter_ns() + 1_000_000_000
        origin.update(
            t0_ns=now,
            stop_ns=now + round(a.duration * 1e9),
            t0_wall_ns=time.time_ns() + 1_000_000_000,
        )

        y_origin.value = now
        y_start.set()

    barrier = threading.Barrier(2, action=release_barrier)
    try:
        for entry in entries["qwen"]:
            prepare(entry)
        prepared_y = 0
        while prepared_y < min(128, len(entries["yolo"])):
            prepare(entries["yolo"][prepared_y])
            prepared_y += 1
        deadline = time.monotonic() + 90
        while any(pub.get_subscription_count() == 0 for pub in pubs.values()):
            if time.monotonic() > deadline:
                raise TimeoutError("No model subscriber")
            rclpy.spin_once(node, timeout_sec=0.02)
        end = time.monotonic() + 3
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
        y_process = ctx.Process(
            target=publish_yolo,
            args=(
                {
                    "offsets": offsets,
                    "ids": [e["request_id"] for e in entries["yolo"]],
                    "run_id": run_id,
                    "image": image,
                },
                y_ready,
                y_start,
                stop,
                y_origin,
                y_sent,
                y_returned,
                y_completed,
                y_failures,
            ),
            daemon=True,
        )
        y_process.start()
        threads = [y_process]
        ready_deadline = time.monotonic() + 90
        while not y_ready.is_set():
            rclpy.spin_once(node, timeout_sec=0.01)
            if not y_process.is_alive() or time.monotonic() > ready_deadline:
                raise RuntimeError("Independent publisher failed preparation")
        if stop.is_set():
            raise RuntimeError("Independent publisher error")
        q_thread = threading.Thread(target=q_sender, daemon=True)
        threads.append(q_thread)
        q_thread.start()
        barrier.wait(timeout=10)
        manifest.update(origin, deadline_ns=origin["stop_ns"] + round(a.drain * 1e9))
        (a.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        while True:
            rclpy.spin_once(node, timeout_sec=0.002)
            while synced_y < y_completed.value:
                entry = entries["yolo"][synced_y]
                apply_send_record(
                    entry,
                    y_sent[synced_y],
                    y_returned[synced_y],
                    origin["t0_ns"] + offsets[synced_y],
                )
                synced_y += 1
            while not y_failures.empty():
                errors.append(y_failures.get())
            now = time.monotonic()
            for rid in list(retire):
                if retire[rid] <= now:
                    node.destroy_subscription(subscriptions.pop(rid))
                    del retire[rid]
            # Do not register thousands of DDS readers before the run or retain completed ones forever.
            target = min(len(entries["yolo"]), y_completed.value + 128)
            for _ in range(min(4, target - prepared_y)):
                prepare(entries["yolo"][prepared_y])
                prepared_y += 1
            pending = [
                e for es in entries.values() for e in es if e["status"] == "pending"
            ]
            if not any(t.is_alive() for t in threads) and not pending:
                break
            if time.perf_counter_ns() > manifest["deadline_ns"]:
                errors.append("Drain deadline exceeded")
                for entry in pending:
                    entry["status"] = "timeout"
                stop.set()
                q_ready.set()
                break
        for thread in threads:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("Publisher did not stop")
        # Give final publication ACKs time to complete before destroying result subscribers.
        end = time.monotonic() + 1.1
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.01)
        for i in range(len(offsets)):
            if y_sent[i]:
                apply_send_record(
                    entries["yolo"][i],
                    y_sent[i],
                    y_returned[i],
                    origin["t0_ns"] + offsets[i],
                )
        issued = [e for es in entries.values() for e in es if e["sent_ns"] is not None]
        ylags = [
            (e["sent_ns"] - e["scheduled_ns"]) / 1e6
            for e in issued
            if e["model"] == "yolo"
        ]
        invalid = sum(e["status"] != "ok" for e in issued)
        v = validity(ylags, invalid + len(errors))
        assert len([e for e in issued if e["model"] == "yolo"]) == len(offsets), (
            "Missed offered requests"
        )
        manifest.update(
            expected={m: sum(e["model"] == m for e in issued) for m in entries},
            received={
                m: sum(e["model"] == m and e["status"] == "ok" for e in issued)
                for m in entries
            },
            errors=errors,
            generator=v,
            pilot_queue=pilot_queue(issued, origin["t0_ns"], a.duration),
        )
        (a.output / "final-requests.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in issued)
        )
        if not v["valid"]:
            raise RuntimeError("Invalid workload/result " + repr(v) + repr(errors))
        manifest["state"] = "PASS"
        print(json.dumps(manifest), flush=True)
    except BaseException as error:
        manifest.update(state="FAIL", error=repr(error), errors=errors)
        raise
    finally:
        stop.set()
        q_ready.set()
        for thread in threads:
            thread.join(timeout=5)
        for i in range(len(offsets)):
            if y_sent[i]:
                apply_send_record(
                    entries["yolo"][i],
                    y_sent[i],
                    y_returned[i],
                    origin["t0_ns"] + offsets[i],
                )
        issued = [e for es in entries.values() for e in es if e["sent_ns"] is not None]
        (a.output / "final-requests.jsonl").write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in issued)
        )
        manifest["end_wall_ns"] = time.time_ns()
        (a.output / "manifest.json").write_text(json.dumps(manifest, indent=2))
        stream.close()
        for sub in list(subscriptions.values()):
            node.destroy_subscription(sub)
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
