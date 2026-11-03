#!/usr/bin/env python3
"""Persistent ROS2 closed-loop C1/workload benchmark. No model or queue changes."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time
import uuid

from aggregate_latency import aggregate

PROMPTS = [
    "Explain GPU resource contention in six concise bullet points.",
    "Describe the responsibilities of an AI model serving platform in six bullet points.",
    "Explain why queue waiting time increases under heavy request traffic.",
    "Describe how to compare two inference systems fairly using latency and throughput.",
    "Explain the differences between a language model workload and an object detection workload.",
]


def request_payload(model, index, mode, maximum, images, run_id):
    if model == "qwen":
        prompt_index = index // 2 if mode == "alternating" else index
        payload = {
            "text": PROMPTS[prompt_index % len(PROMPTS)],
            "max_new_tokens": maximum,
        }
        if mode == "alternating":
            # Counterbalanced paired basic/tokens measurements on identical inputs.
            payload["timing_mode"] = ("basic", "tokens")[(index + index // 2) % 2]
        else:
            payload["timing_mode"] = mode
    else:
        payload = {"image_base64": images[index % len(images)]}
    payload["run_id"] = run_id
    return payload


def needs_more(model, counts, target, warmup, both):
    return counts[model] < target or (
        not warmup and both and model == "yolo" and counts["qwen"] < target
    )


def main():
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from std_msgs.msg import String

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", choices=["qwen", "yolo", "both"], required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--samples", type=int, default=30)
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--max-new-tokens", type=int, default=128)
    p.add_argument(
        "--timing-mode", choices=["basic", "tokens", "alternating"], default="tokens"
    )
    p.add_argument("--timeout", type=float, default=180)
    p.add_argument("--assets", type=Path, default=Path.home() / "cj-containers/assets")
    a = p.parse_args()
    if a.samples < 1 or a.warmup < 1 or a.max_new_tokens < 1:
        p.error("positive samples, warmup and max-new-tokens required")
    a.output.mkdir(parents=True, exist_ok=False)
    models = ["qwen", "yolo"] if a.models == "both" else [a.models]
    images = []
    image_metadata = []
    if "yolo" in models:
        for name in ("bus.jpg", "zidane.jpg"):
            data = (a.assets / name).read_bytes()
            images.append(base64.b64encode(data).decode("ascii"))
            image_metadata.append(
                {"name": name, "sha256": hashlib.sha256(data).hexdigest()}
            )
    run_id = a.output.name + "_" + uuid.uuid4().hex[:8]
    manifest = {
        "schema": 1,
        "run_id": run_id,
        "models": models,
        "samples_minimum": a.samples,
        "warmup_per_model": a.warmup,
        "max_new_tokens": a.max_new_tokens,
        "timing_mode": a.timing_mode,
        "prompts": PROMPTS,
        "images": image_metadata,
        "concurrency_per_model": 1,
        "load": "closed-loop; YOLO continues until Qwen completes in both mode",
        "e2e_boundary": "before request JSON encoding/publish -> matching response parsed",
        "excluded": [
            "initial discovery",
            "input image read/base64",
            "output image drawing/saving",
        ],
        "percentile_method": "linear interpolation (n-1)*p",
        "start_wall_ns": time.time_ns(),
        "measurement_seconds": {},
        "state": "running",
    }
    rows = []
    rclpy.init(args=[])
    node = rclpy.create_node("bench_" + uuid.uuid4().hex)
    publishers = {
        m: node.create_publisher(
            String,
            f"/{m}/request",
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        for m in models
    }
    pending = {}
    counts = {m: 0 for m in models}
    starts, ends = {}, {}
    out = (a.output / "requests.jsonl").open("x")
    setup = time.perf_counter_ns()
    try:
        deadline = time.monotonic() + 300
        while any(pub.get_subscription_count() == 0 for pub in publishers.values()):
            if time.monotonic() > deadline:
                raise TimeoutError("Model subscriber not discovered")
            rclpy.spin_once(node, timeout_sec=0.05)
        manifest["setup_discovery_ms"] = (time.perf_counter_ns() - setup) / 1e6

        def on_response(model, rid, message):
            receive = time.perf_counter_ns()
            reply = json.loads(message.data)
            if (
                reply.get("request_id") != rid
                or model not in pending
                or pending[model]["request_id"] != rid
            ):
                return
            end = time.perf_counter_ns()
            entry = pending[model]
            entry.update(
                status=reply.get("status", "error"),
                response=reply,
                received_ns=end,
                response_parse_ms=(end - receive) / 1e6,
                request_e2e_ms=(end - entry["sent_ns"]) / 1e6,
            )
            entry["done"] = True

        def launch(model, warmup):
            i = counts[model]
            mode = (
                "tokens" if warmup and a.timing_mode == "alternating" else a.timing_mode
            )
            payload = request_payload(model, i, mode, a.max_new_tokens, images, run_id)
            rid = "r_" + uuid.uuid4().hex
            payload["request_id"] = rid
            payload_hash = hashlib.sha256(
                json.dumps(
                    {
                        k: v
                        for k, v in payload.items()
                        if k not in ("request_id", "run_id", "timing_mode")
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            sub = node.create_subscription(
                String,
                f"/{model}/result/{rid}",
                lambda msg, m=model, r=rid: on_response(m, r, msg),
                1,
            )
            entry = {
                "model": model,
                "run_id": run_id,
                "request_id": rid,
                "index": i,
                "warmup": warmup,
                "timing_mode": payload.get("timing_mode", "basic"),
                "input_hash": payload_hash,
                "subscription": sub,
                "done": False,
                "send_wall_ns": time.time_ns(),
            }
            pending[model] = entry
            # Serialization deliberately inside the E2E boundary.
            entry["sent_ns"] = time.perf_counter_ns()
            if not warmup:
                starts.setdefault(model, entry["sent_ns"])
            publishers[model].publish(
                String(data=json.dumps(payload, ensure_ascii=False))
            )

        for warmup in (True, False):
            counts = {m: 0 for m in models}
            target = a.warmup if warmup else a.samples
            while True:
                for model in models:
                    if model in pending and not pending[model]["done"]:
                        elapsed = (
                            time.perf_counter_ns() - pending[model]["sent_ns"]
                        ) / 1e9
                        if elapsed > a.timeout:
                            pending[model].update(
                                done=True,
                                status="timeout",
                                received_ns=time.perf_counter_ns(),
                                request_e2e_ms=elapsed * 1000,
                            )
                    if model in pending and pending[model]["done"]:
                        entry = pending.pop(model)
                        node.destroy_subscription(entry.pop("subscription"))
                        entry.pop("done")
                        rows.append(entry)
                        out.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        out.flush()
                        counts[model] += 1
                        if not warmup:
                            ends[model] = entry["received_ns"]
                        if entry["status"] != "ok":
                            raise RuntimeError(
                                f"{model} request failed: {entry['status']}"
                            )

                def needs(model):
                    return needs_more(model, counts, target, warmup, a.models == "both")

                if all(not needs(m) for m in models) and not pending:
                    break
                for model in models:
                    if model not in pending and needs(model):
                        launch(model, warmup)
                rclpy.spin_once(node, timeout_sec=0.001)
            print(
                json.dumps(
                    {
                        "stage": "warmup_done" if warmup else "measurement_done",
                        "counts": counts,
                    }
                ),
                flush=True,
            )
        manifest["state"] = "PASS"
    except Exception as error:
        manifest.update(state="FAIL", error=repr(error))
        raise
    finally:
        out.close()
        manifest["end_wall_ns"] = time.time_ns()
        manifest["measurement_seconds"] = {
            m: (ends[m] - starts[m]) / 1e9 for m in starts if m in ends
        }
        (a.output / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        )
        summary = aggregate(rows, manifest["measurement_seconds"])
        (a.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        node.destroy_node()
        rclpy.try_shutdown()
    print(json.dumps({"state": manifest["state"], "output": str(a.output)}))


if __name__ == "__main__":
    main()
