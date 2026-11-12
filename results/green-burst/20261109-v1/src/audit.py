"""Independent complete-burst audit, component clocks, fixed work and live publication coverage."""

import argparse
import json
from pathlib import Path
import re
from metrics import burst_completion, request_parts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    workload = json.loads((a.root / "workload.json").read_text())
    reports = []
    for folder in ("warmup", "results"):
        for directory in sorted((a.root / folder).iterdir()):
            if not directory.is_dir():
                continue
            manifest = json.loads((directory / "manifest.json").read_text())
            assert manifest["state"] == "PASS"
            expected = (
                {"qwen": 3, "yolo": 30}
                if folder == "warmup"
                else {"qwen": 10, "yolo": 300}
            )
            assert manifest["expected"] == expected and manifest["ros_domain"] == 74
            rows = [
                json.loads(line)
                for line in (directory / "final-requests.jsonl")
                .read_text()
                .splitlines()
            ]
            summary = burst_completion(rows, manifest["batch_t0_perf_ns"], expected)
            match = re.match(r"q(\d+)-y(\d+)", directory.name)
            sms = (
                {"qwen": int(match[1]), "yolo": int(match[2])}
                if match
                else {"qwen": 48, "yolo": 48}
            )
            failures = []
            for r in rows:
                response = r["response"]
                timing = response["timings_ms"]
                model = r["model"]
                assert (
                    response["request_id"] == r["request_id"]
                    and response["run_id"] == manifest["run_id"]
                )
                assert (
                    response["status"] == "ok"
                    and response["assigned_sms"] == sms[model]
                    and response["green_enabled"] == bool(match)
                )
                assert r["sent_ns"] <= response["server_enqueued_perf_ns"] + 1000000
                assert (
                    response["server_started_perf_ns"]
                    >= response["server_enqueued_perf_ns"]
                )
                assert (
                    response["model_start_perf_ns"]
                    >= response["server_started_perf_ns"]
                )
                assert response["model_end_perf_ns"] >= response["model_start_perf_ns"]
                assert (
                    abs(
                        (
                            response["server_started_perf_ns"]
                            - response["server_enqueued_perf_ns"]
                        )
                        / 1e6
                        - response["queue_wait_ms"]
                    )
                    < 0.001
                )
                e2e = (r["received_ns"] - r["sent_ns"]) / 1e6
                assert abs(e2e - r["request_e2e_ms"]) < 1e-6
                key = "generate_wall_ms" if model == "qwen" else "predict_wall_ms"
                parts = request_parts(
                    e2e,
                    response["queue_wait_ms"],
                    response["processing_ms"],
                    timing[key],
                    timing["gpu_forward_span_ms"],
                )
                assert parts == r["components"]
                assert (
                    abs(
                        sum(v for k, v in parts.items() if k != "gpu_forward_span_ms")
                        - e2e
                    )
                    < 1e-6
                )
                assert 0 < timing["gpu_forward_span_ms"] <= timing[key] + 1
                if (
                    parts["transport_client_residual_ms"] < 0
                    or parts["server_nonpipeline_ms"] < 0
                ):
                    failures.append(r["request_id"])
                if model == "qwen":
                    assert (
                        response["input_tokens"] == 512
                        and response["output_tokens"] == 128
                    )
                    assert response["input_ids_sha256"] == workload["input_ids_sha256"]
                    assert response["gpu_forward_lengths"] == [512] + [1] * 127
                    assert len(response["gpu_forward_event_ms"]) == 128
                    assert (
                        abs(
                            sum(response["gpu_forward_event_ms"])
                            - timing["gpu_forward_span_ms"]
                        )
                        < 1e-6
                    )
                else:
                    assert (
                        response["gpu_forward_shape"] == [1, 3, 640, 640]
                        and len(response["detections"]) == 5
                    )
            publication = {}
            for model in expected:
                ids = {r["request_id"] for r in rows if r["model"] == model}
                events = {}
                path = a.root / "logs" / f"{directory.name}-{model}.log"
                for line in path.read_text().splitlines():
                    start = line.find('{"event"')
                    if start < 0:
                        continue
                    try:
                        event = json.loads(line[start:])
                    except ValueError:
                        continue
                    assert event.get("event") != "queue_full", (
                        "Application queue overflow"
                    )
                    if (
                        event.get("event") == "publication_finished"
                        and event.get("request_id") in ids
                    ):
                        events[event["request_id"]] = event
                publication[model] = {
                    "expected": len(ids),
                    "captured": len(events),
                    "complete": len(events) == len(ids),
                    "ack_failed": sum(
                        not e.get("acknowledged", False) for e in events.values()
                    ),
                }
            reports.append(
                {
                    "run": directory.name,
                    "kind": folder,
                    "state": "PASS",
                    "counts": summary["completed"],
                    "overall_completion_ms": summary["overall_completion_ms"],
                    "negative_residual_ids": failures,
                    "publications": publication,
                }
            )
    assert sum(r["kind"] == "results" for r in reports) == 21
    assert sum(r["kind"] == "warmup" for r in reports) == 7
    (a.root / "verification/protocol-audit.json").write_text(
        json.dumps(reports, indent=2)
    )
    print(
        json.dumps(
            {
                "runs": len(reports),
                "requests": sum(sum(r["counts"].values()) for r in reports),
                "log_gaps": [
                    (r["run"], m)
                    for r in reports
                    for m, v in r["publications"].items()
                    if not v["complete"]
                ],
                "negative_residuals": sum(
                    len(r["negative_residual_ids"]) for r in reports
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
