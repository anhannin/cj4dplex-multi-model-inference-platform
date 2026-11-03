"""Validate and compare completed five-phase exploratory measurements."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
from aggregate_latency import stats

PHASES = [
    "01-qwen-only",
    "02-yolo-only",
    "03-both-resident-qwen",
    "04-both-resident-yolo",
    "05-concurrent",
]


def compare_outputs(reference, current):
    assert len(reference) == len(current)
    assert all(a[0] == b[0] for a, b in zip(reference, current)), (
        "Input workload changed"
    )
    assert all(a[2] == b[2] for a, b in zip(reference, current)), (
        "Output token count changed"
    )
    different = sum(a[1] != b[1] for a, b in zip(reference, current))
    return {
        "exact_text_match": different == 0,
        "different_output_requests": different,
        "input_hashes_match": True,
        "output_token_counts_match": True,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    a = p.parse_args()
    output = []
    validation = {}
    baseline = {}
    for phase in PHASES:
        root = a.root / "phases" / phase
        manifest = json.loads((root / "manifest.json").read_text())
        assert manifest["state"] == "PASS", (phase, manifest)
        summary = json.loads((root / "summary.json").read_text())
        rows = [
            json.loads(x)
            for x in (root / "joined-requests.jsonl").read_text().splitlines()
        ]
        measured = [r for r in rows if not r["warmup"]]
        ids = [r["request_id"] for r in rows]
        assert len(set(ids)) == len(ids)
        assert all(r["server_events_complete"] for r in rows)
        assert all(r["status"] == "ok" for r in rows)
        assert all(r["request_e2e_ms"] >= 0 for r in rows)
        pods = json.loads((root / "pods.json").read_text())["items"]
        expected = 1 if phase in PHASES[:2] else 2
        assert len(pods) == expected, (phase, len(pods))
        assert all(
            c["ready"] and c["restartCount"] == 0
            for pod in pods
            for c in pod["status"]["containerStatuses"]
        )
        output_comparison = None
        for model in summary:
            model_rows = [r for r in measured if r["model"] == model]
            count = 30 if model == "qwen" or phase == "05-concurrent" else 300
            assert len(model_rows) >= count
            if phase != "05-concurrent" or model == "qwen":
                assert len(model_rows) == count
            if model == "qwen":
                for r in model_rows:
                    response = r["response"]
                    assert response["timing_mode"] == "tokens"
                    assert response["output_tokens"] <= 128
                    assert len(response["itl_ms"]) == response["output_tokens"] - 1
                outputs = [
                    (
                        r["input_hash"],
                        hashlib.sha256(r["response"]["text"].encode()).hexdigest(),
                        r["response"]["output_tokens"],
                    )
                    for r in model_rows
                ]
                if phase == "01-qwen-only":
                    baseline[model] = outputs
                output_comparison = compare_outputs(baseline[model], outputs)
        host = [
            json.loads(x)
            for x in (root / "host-metrics.jsonl").read_text().splitlines()
        ]
        lo = min(r["sent_ns"] for r in measured)
        hi = max(r["received_ns"] for r in measured)
        host = [r for r in host if lo <= r["monotonic_ns"] <= hi]
        resources = {
            "samples": len(host),
            "host_cpu_percent": stats([r.get("host_cpu_percent") for r in host]),
            "host_used_available_based_gib": stats(
                [
                    (r["memory_total_bytes"] - r["memory_available_bytes"]) / 2**30
                    for r in host
                ]
            ),
        }
        for i, name in enumerate(("gpu_util_percent", "gpu_temp_c", "gpu_power_w")):
            values = []
            for r in host:
                try:
                    values.append(float(r["gpu_query_csv"].split(",")[i].strip()))
                except (KeyError, ValueError, IndexError):
                    pass
            resources[name] = stats(values)
        ack_failures = 0
        for model in summary:
            for line in (root / f"{model}-server.log").read_text().splitlines():
                start = line.find('{"event"')
                if start < 0:
                    continue
                event = json.loads(line[start:])
                if (
                    event.get("event") == "publication_finished"
                    and event.get("run_id") == manifest["run_id"]
                    and not event.get("acknowledged")
                ):
                    ack_failures += 1
        validation[phase] = {
            "qwen_output_comparison_to_solo": output_comparison,
            "ack_failures_including_warmup": ack_failures,
            "samples_by_model": {m: s["attempted"] for m, s in summary.items()},
            "missing_server_events": sum(not r["server_events_complete"] for r in rows),
            "negative_residuals": sum(
                r.get("negative_residual_flag", False) for r in measured
            ),
            "resources": resources,
        }
        for model, s in summary.items():

            def mean(k):
                return s.get(k, {}).get("mean")

            row = {
                "phase": phase,
                "model": model,
                "n": s["attempted"],
                "failed": s["failed"],
                "e2e_mean_ms": mean("request_e2e_ms"),
                "e2e_p95_ms": s["request_e2e_ms"]["p95"],
                "queue_mean_ms": mean("queue_wait_ms"),
                "processing_mean_ms": mean("processing_ms"),
                "inference_mean_ms": mean(
                    "generate_wall_ms" if model == "qwen" else "yolo_inference_ms"
                ),
                "generate_ttft_mean_ms": mean("generate_ttft_ms"),
                "tpot_mean_ms": mean("tpot_ms"),
                "throughput_requests_s": s["successful_requests_per_second"],
                "worker_busy_mean_ms": mean("worker_busy_ms"),
                "result_discovery_mean_ms": mean("result_discovery_ms"),
                "transport_client_residual_mean_ms": mean(
                    "transport_client_residual_ms"
                ),
            }
            output.append(row)
    (a.root / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    (a.root / "comparison.json").write_text(json.dumps(output, indent=2) + "\n")
    with (a.root / "comparison.csv").open("w") as f:
        w = csv.DictWriter(f, fieldnames=list(output[0]))
        w.writeheader()
        w.writerows(output)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
