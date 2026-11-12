"""Common-origin finite-batch completion and non-overlapping host accounting."""

import math


def burst_completion(rows, t0, expected):
    counts = {model: 0 for model in expected}
    seen = set()
    ends = {}
    for row in rows:
        if (
            row["request_id"] in seen
            or row["model"] not in counts
            or row["status"] != "ok"
        ):
            raise ValueError("Duplicate/unexpected/failed response")
        seen.add(row["request_id"])
        counts[row["model"]] += 1
        if row["received_ns"] < row["sent_ns"] or row["sent_ns"] < t0:
            raise ValueError("Invalid timestamp order")
        ends[row["model"]] = max(ends.get(row["model"], t0), row["received_ns"])
    if counts != expected:
        raise ValueError(f"Incomplete batch: {counts} != {expected}")
    values = {model: (end - t0) / 1e6 for model, end in ends.items()}
    return {
        "model_completion_ms": values,
        "overall_completion_ms": max(values.values()),
        "completed": counts,
    }


def request_parts(e2e, queue, processing, pipeline, gpu):
    values = (e2e, queue, processing, pipeline, gpu)
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Finite nonnegative durations required")
    return {
        "app_queue_ms": queue,
        "model_pipeline_ms": pipeline,
        "server_nonpipeline_ms": processing - pipeline,
        "transport_client_residual_ms": e2e - queue - processing,
        "gpu_forward_span_ms": gpu,
    }


def select_candidate(rows, tie=0.03):
    fastest = min(rows, key=lambda r: r["total_mean_ms"])
    candidates = [
        r for r in rows if r["total_mean_ms"] <= fastest["total_mean_ms"] * (1 + tie)
    ]
    selected = min(candidates, key=lambda r: (r["yolo_mean_ms"], r["total_mean_ms"]))
    return {
        "strict_fastest": fastest["label"],
        "balanced_selected": selected["label"],
        "within_3pct_candidates": [r["label"] for r in candidates],
        "note": "descriptive predeclared makespan tie heuristic, not statistical equivalence or SLO",
    }
