"""Independent sustained-run audit and per-run-first SLO statistics; no ROS needed."""

import argparse
import csv
import json
import math
from pathlib import Path
import statistics

try:
    from .protocol import percentile, scheduled_offsets
except ImportError:
    from protocol import percentile, scheduled_offsets


CONDITIONS = ("control", "mps-only", "static-q8-y40", "static-q16-y32")


def distribution(values):
    a = list(values)
    if any(not math.isfinite(x) for x in a):
        raise ValueError("Nonfinite metric")
    return {
        "n": len(a),
        "mean": statistics.mean(a) if a else None,
        "p50": percentile(a, 50),
        "p95": percentile(a, 95),
        "min": min(a) if a else None,
        "max": max(a) if a else None,
        "stdev": statistics.stdev(a) if len(a) > 1 else None,
    }


def grouped_decision(candidate, baseline):
    q = 100 * (
        candidate["qwen"]["e2e_ms"]["p95"] / baseline["qwen"]["e2e_ms"]["p95"] - 1
    )
    y = 100 * (
        candidate["yolo"]["e2e_ms"]["p95"] / baseline["yolo"]["e2e_ms"]["p95"] - 1
    )
    clean = candidate["errors"] == 0 and baseline["errors"] == 0
    return {
        "qwen_change_pct": q,
        "yolo_change_pct": y,
        "qwen_pass": clean and q <= 0,
        "yolo_pass": clean
        and candidate["yolo"]["e2e_ms"]["p95"]
        <= 0.8 * baseline["yolo"]["e2e_ms"]["p95"],
        "both_pass": clean
        and q <= 0
        and candidate["yolo"]["e2e_ms"]["p95"]
        <= 0.8 * baseline["yolo"]["e2e_ms"]["p95"],
    }


def queue_series(rows, t0, duration, step=1):
    selected = [r for r in rows if r["model"] == "yolo" and r["status"] == "ok"]
    return [
        (
            i * step,
            sum(
                r["response"]["server_enqueued_perf_ns"]
                <= t0 + i * step * 1e9
                < r["response"]["server_started_perf_ns"]
                for r in selected
            ),
        )
        for i in range(math.floor(duration / step) + 1)
    ]


def validate_rows(rows, manifest, work):
    counts = {m: sum(r["model"] == m for r in rows) for m in ("qwen", "yolo")}
    if counts != manifest["expected"] or len({r["request_id"] for r in rows}) != len(
        rows
    ):
        raise ValueError("Missing/duplicate request records")
    if manifest["phase"] == "main" and len(
        [r for r in rows if r["model"] == "yolo"]
    ) != len(scheduled_offsets(manifest["rate"], manifest["duration_s"])):
        raise ValueError("Offered workload does not match fixed schedule")
    qlast = None
    for r in sorted(rows, key=lambda x: x["sent_ns"]):
        if r["run_id"] != manifest["run_id"] or not manifest["t0_ns"] <= r["sent_ns"]:
            raise ValueError("Wrong run/clock")
        if r["status"] != "ok":
            continue
        response = r["response"]
        if (
            response["status"] != "ok"
            or response["request_id"] != r["request_id"]
            or response["run_id"] != manifest["run_id"]
        ):
            raise ValueError("Wrong result identity/status")
        if (
            r["received_ns"] < r["sent_ns"]
            or abs(r["request_e2e_ms"] - (r["received_ns"] - r["sent_ns"]) / 1e6) > 1e-6
        ):
            raise ValueError("Wrong E2E")
        if response["green_enabled"]:
            raise ValueError("Green unexpectedly enabled")
        expected = {"static-q8-y40": (8, 40), "static-q16-y32": (16, 32)}.get(
            manifest["condition"], (48, 48)
        )
        if response["assigned_sms"] != expected[0 if r["model"] == "qwen" else 1]:
            raise ValueError("Wrong resource partition")
        enq, start, ms, me = [
            response[k]
            for k in (
                "server_enqueued_perf_ns",
                "server_started_perf_ns",
                "model_start_perf_ns",
                "model_end_perf_ns",
            )
        ]
        if not r["sent_ns"] <= enq <= start <= ms <= me <= r["received_ns"]:
            raise ValueError("Cross-process timestamp order")
        if abs(response["queue_wait_ms"] - (start - enq) / 1e6) > 0.01:
            raise ValueError("Queue timestamp mismatch")
        if r["model"] == "qwen":
            if (
                not response["input_tokens"] == 512
                or response["output_tokens"] != 128
                or response["gpu_forward_lengths"] != [512] + [1] * 127
                or response["input_ids_sha256"] != work["input_ids_sha256"]
            ):
                raise ValueError("Qwen workload changed")
            if r["sent_ns"] >= manifest["stop_ns"] or (
                qlast is not None and r["sent_ns"] < qlast
            ):
                raise ValueError("Qwen C1/stop violation")
            qlast = r["received_ns"]
        else:
            if response["gpu_forward_shape"] != [1, 3, 640, 640]:
                raise ValueError("YOLO workload changed")
            if r["scheduled_ns"] != manifest["t0_ns"] + round(
                r["index"] * 1e9 / manifest["rate"]
            ):
                raise ValueError("YOLO schedule changed")
    return {
        "requests": len(rows),
        "errors": sum(r["status"] != "ok" for r in rows),
        "state": "PASS",
    }


def model_stats(rows, model, manifest):
    selected = [r for r in rows if r["model"] == model]
    good = [r for r in selected if r["status"] == "ok"]
    metrics = {
        "e2e_ms": distribution(r["request_e2e_ms"] for r in good),
        "scheduled_e2e_ms": distribution(r["scheduled_e2e_ms"] for r in good),
        "queue_ms": distribution(r["response"]["queue_wait_ms"] for r in good),
        "processing_ms": distribution(r["response"]["processing_ms"] for r in good),
        "schedule_lag_ms": distribution(
            (r["sent_ns"] - r["scheduled_ns"]) / 1e6 for r in selected
        ),
        "errors": sum(r["status"] != "ok" for r in selected),
        "issued": len(selected),
        "completed": len(good),
        "completed_by_stop": sum(r["received_ns"] <= manifest["stop_ns"] for r in good),
    }
    keys = (
        "generate_wall_ms",
        "gpu_prefill_span_ms",
        "gpu_decode_total_span_ms",
        "gpu_decode_ms_per_token",
        "generate_ttft_ms",
        "server_ttft_ms",
        "tpot_ms",
        "predict_wall_ms",
        "gpu_forward_span_ms",
        "yolo_preprocess_ms",
        "yolo_postprocess_ms",
        "predict_overhead_ms",
    )
    for k in keys:
        vals = [
            r["response"]["timings_ms"][k]
            for r in good
            if k in r["response"]["timings_ms"]
        ]
        if vals:
            metrics[k] = distribution(vals)
    pipeline = "generate_wall_ms" if model == "qwen" else "predict_wall_ms"
    metrics["server_nonpipeline_ms"] = distribution(
        r["response"]["processing_ms"] - r["response"]["timings_ms"][pipeline]
        for r in good
    )
    metrics["transport_client_residual_ms"] = distribution(
        r["request_e2e_ms"]
        - r["response"]["queue_wait_ms"]
        - r["response"]["processing_ms"]
        for r in good
    )
    metrics["issue_rate_rps"] = len(selected) / manifest["duration_s"]
    metrics["goodput_by_stop_rps"] = (
        metrics["completed_by_stop"] / manifest["duration_s"]
    )
    metrics["cohort_completion_s"] = max(
        ((r["received_ns"] - manifest["t0_ns"]) / 1e9 for r in good), default=0
    )
    metrics["drain_s"] = max(0, metrics["cohort_completion_s"] - manifest["duration_s"])
    if model == "qwen":
        metrics["output_tokens_per_window_s"] = (
            metrics["completed_by_stop"] * 128 / manifest["duration_s"]
        )
        metrics["output_tokens_per_cohort_s"] = (
            len(good) * 128 / max(1e-9, metrics["cohort_completion_s"])
        )
    return metrics


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    root = a.root
    status = json.loads((root / "verification/controller-status.json").read_text())
    if status["state"] != "PASS" or status["restoration"] != "PASS":
        raise ValueError("Controller not completed/restored")
    work = json.loads((root / "workload.json").read_text())
    plan = json.loads((root / "schedule.json").read_text())
    if len(plan) != 40 or len(status["completed"]) != 40:
        raise ValueError("Incomplete experiment")
    trials = []
    raw = {}
    audits = []
    for item in plan:
        folder = root / "results" / item["label"]
        manifest = json.loads((folder / "manifest.json").read_text())
        rows = [
            json.loads(line)
            for line in (folder / "final-requests.jsonl").read_text().splitlines()
        ]
        if manifest["state"] != "PASS" or not manifest["generator"]["valid"]:
            raise ValueError("Invalid run " + item["label"])
        audit = validate_rows(rows, manifest, work)
        audits.append({"label": item["label"], **audit})
        t = {
            **item,
            "duration_s": manifest["duration_s"],
            "errors": audit["errors"],
            "generator": manifest["generator"],
            "queue_series": queue_series(
                rows, manifest["t0_ns"], manifest["duration_s"]
            ),
            **{m: model_stats(rows, m, manifest) for m in ("qwen", "yolo")},
        }
        trials.append(t)
        raw.setdefault((item["rate"], item["condition"]), []).append((rows, manifest))
    groups = []
    for rate in sorted({t["rate"] for t in trials}):
        current = []
        for condition in CONDITIONS:
            ts = [
                t for t in trials if t["rate"] == rate and t["condition"] == condition
            ]
            if len(ts) != 5:
                raise ValueError("Missing replicate")
            allrows = [r for records, _ in raw[(rate, condition)] for r in records]
            g = {
                "rate": rate,
                "condition": condition,
                "n_trials": 5,
                "errors": sum(t["errors"] for t in ts),
            }
            for m in ("qwen", "yolo"):
                keys = [
                    k for k, v in ts[0][m].items() if isinstance(v, dict) and "p95" in v
                ]
                g[m] = {
                    k: {
                        "mean": statistics.mean(t[m][k]["mean"] for t in ts),
                        "p95": statistics.mean(t[m][k]["p95"] for t in ts),
                        "run_p95": distribution(t[m][k]["p95"] for t in ts),
                        "run_mean": distribution(t[m][k]["mean"] for t in ts),
                    }
                    for k in keys
                }
                g[m]["pooled_e2e_ms"] = distribution(
                    r["request_e2e_ms"]
                    for r in allrows
                    if r["model"] == m and r["status"] == "ok"
                )
                for key in (
                    "issued",
                    "completed",
                    "completed_by_stop",
                    "issue_rate_rps",
                    "goodput_by_stop_rps",
                    "drain_s",
                ):
                    g[m][key] = distribution(t[m][key] for t in ts)
                if m == "qwen":
                    g[m]["output_tokens_per_cohort_s"] = distribution(
                        t[m]["output_tokens_per_cohort_s"] for t in ts
                    )
            current.append(g)
        baseline = next(g for g in current if g["condition"] == "control")
        for g in current:
            g["slo"] = grouped_decision(g, baseline)
            g["paired_changes"] = {
                m: [
                    100
                    * (
                        t[m]["e2e_ms"]["p95"]
                        / next(
                            b
                            for b in trials
                            if b["rate"] == rate
                            and b["round"] == t["round"]
                            and b["condition"] == "control"
                        )[m]["e2e_ms"]["p95"]
                        - 1
                    )
                    for t in trials
                    if t["rate"] == rate and t["condition"] == g["condition"]
                ]
                for m in ("qwen", "yolo")
            }
            g["pooled_slo_sensitivity"] = grouped_decision(
                {
                    "errors": g["errors"],
                    **{m: {"e2e_ms": g[m]["pooled_e2e_ms"]} for m in ("qwen", "yolo")},
                },
                {
                    "errors": baseline["errors"],
                    **{
                        m: {"e2e_ms": baseline[m]["pooled_e2e_ms"]}
                        for m in ("qwen", "yolo")
                    },
                },
            )
        groups.extend(current)
    out = root / "analysis"
    out.mkdir(exist_ok=True)
    summary = {
        "decision_unit": "mean of 5 per-run request E2E p95; rates separate",
        "scope": "mixed closed-loop Qwen C1 and fixed-rate open-loop YOLO; full issued cohort including drain",
        "groups": groups,
        "trials": trials,
        "requests": sum(a["requests"] for a in audits),
        "audits": audits,
        "limits": [
            "Qwen ~10 samples/run, descriptive p95; 0% observational gate is not equivalence proof",
            "CUDA event is forward elapsed span, not pure GPU execution; models batch1",
            "pilot control-only rate selection; 120s window not long-term stability proof",
        ],
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (root / "verification/independent-audit.json").write_text(
        json.dumps(
            {"state": "PASS", "trials": audits, "requests": summary["requests"]},
            indent=2,
        )
    )
    with (out / "trials.csv").open("w") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "label",
                "condition",
                "round",
                "rate",
                "model",
                "N",
                "e2e_mean_ms",
                "e2e_p95_ms",
                "queue_mean_ms",
                "queue_p95_ms",
                "pipeline_mean_ms",
                "GPU_forward_mean_ms",
                "drain_s",
                "errors",
            ]
        )
        for t in trials:
            for m in ("qwen", "yolo"):
                d = t[m]
                pipe = "generate_wall_ms" if m == "qwen" else "predict_wall_ms"
                writer.writerow(
                    [
                        t["label"],
                        t["condition"],
                        t["round"],
                        t["rate"],
                        m,
                        d["issued"],
                        d["e2e_ms"]["mean"],
                        d["e2e_ms"]["p95"],
                        d["queue_ms"]["mean"],
                        d["queue_ms"]["p95"],
                        d[pipe]["mean"],
                        d["gpu_forward_span_ms"]["mean"],
                        d["drain_s"],
                        d["errors"],
                    ]
                )
    print(
        json.dumps(
            {
                "state": "PASS",
                "requests": summary["requests"],
                "trials": len(trials),
                "SLO": [
                    {k: g[k] for k in ("rate", "condition", "slo")} for g in groups
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
