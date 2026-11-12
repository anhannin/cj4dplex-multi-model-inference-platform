"""Analyze actual models under MPS, not kernel spans under switching client contexts."""

import argparse
import gzip
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kernel_overlap"))
from analysis import duration, fit_clock, intersect
from analyze_reports import case_analysis, clip, text_events
from scheduler_analysis import residencies
from evidence import associated_residence

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
p.add_argument("--case", default="native-static-q16-y32")
p.add_argument(
    "--reference",
    action="store_true",
    help="Record a reference even if the predeclared50ms conservative gate is not met",
)
a = p.parse_args()
root = a.root
model = case_analysis(root, a.case, False)
with gzip.open(root / "analysis" / f"{a.case}-intervals.json.gz", "rt") as f:
    kernels = json.load(f)
lo, hi = kernels["window_ns"]
folder = root / "validation" / a.case / "scheduler"
with sqlite3.connect(folder / "trace.sqlite") as conn:
    marks = {
        name: t
        for t, end, name in text_events(conn)
        if name.startswith("clock:scheduler:")
    }
    records = [
        json.loads(line) for line in (folder / "clocks.jsonl").read_text().splitlines()
    ]
    assert all(r["name"] in marks for r in records)
    clock = fit_clock([{**r, "trace_ns": marks[r["name"]]} for r in records])
    mapping = clock["map"]
    rows = conn.execute(
        "SELECT tag,contextId,timestamp,globalPid,seqNo FROM GPU_CONTEXT_SWITCH_EVENTS ORDER BY timestamp"
    ).fetchall()
    assert all(y[4] == x[4] + 1 for x, y in zip(rows, rows[1:]))
    intervals, tail = residencies(
        [(tag, c, mapping(t), (pid >> 24) & 0xFFFFFF) for tag, c, t, pid, seq in rows]
    )
    assert tail is None or tail[0] >= hi
    membership = json.loads(
        (root / "verification" / f"{a.case}-pre-mps-membership.json").read_text()
    )
    server = int(membership["server"])
    clients = [int(v) for v in membership["clients"]]
    assert set(clients) == set(membership["models"].values())
    assert len(set(clients)) == 2
    resident = clip(associated_residence(intervals, server, clients), lo, hi)
    overlap = kernels["intersection"]
    guard_ns = max(
        200000,
        math.ceil(
            clock["empirical_alignment_error_ns"]
            + max(model["empirical_alignment_tolerance_ns"].values())
            + 1000
        ),
    )
    guarded = [
        (start + guard_ns, end - guard_ns)
        for start, end, ctx, pid in intervals
        if pid in {server, *clients}
        if end - start > 2 * guard_ns
    ]
    safe = intersect(overlap, guarded)
    eroded = {}
    for name in ("qwen", "yolo"):
        error = model["empirical_alignment_tolerance_ns"][name]
        eroded[name] = [
            (x + error, y - error) for x, y in kernels[name] if y - x > 2 * error
        ]
    conservative = intersect(intersect(eroded["qwen"], eroded["yolo"]), guarded)
    metrics = {}
    for metric in (6, 7, 8, 9, 16):
        vals = [
            v
            for t, v in conn.execute(
                "SELECT timestamp,value FROM GPU_METRICS WHERE metricId=?", (metric,)
            )
            if lo <= mapping(t) < hi
        ]
        assert vals and min(vals) >= 0 and max(vals) <= 100
        metrics[str(metric)] = {
            "samples": len(vals),
            "mean_percent": statistics.mean(vals),
            "max_percent": max(vals),
        }
    output = {
        "model_trace": model,
        "mps_server_host_pid": server,
        "mps_clients_host_pid": clients,
        "scheduler_clock": {k: v for k, v in clock.items() if k != "map"},
        "context_events": len(rows),
        "internal_sequence_gaps": 0,
        "context_attribution_note": "This driver attributes MPS scheduling events to member client PIDs, not the server PID. Membership verified separately; never infer attribution from server name alone.",
        "context_pids": sorted(
            {(pid >> 24) & 0xFFFFFF for tag, c, t, pid, seq in rows}
        ),
        "mps_associated_hardware_resident_ms": duration(resident) / 1e6,
        "cross_model_kernel_overlap_in_mps_hardware_residence_ms": duration(
            intersect(overlap, resident)
        )
        / 1e6,
        "transition_guard_ns": guard_ns,
        "overlap_away_from_context_transitions_ms": duration(safe) / 1e6,
        "conservative_overlap_in_uninterrupted_mps_residence_ms": duration(conservative)
        / 1e6,
        "device_metrics": metrics,
        "note": "Kernel elapsed spans inside uninterrupted MPS-associated context residence, with two actual-model clients. Device metrics not process-attributed. No Green API. Static status/SMcounts taken from actual partition-plan case; clientmembership captured before warmup and hostPID reconfirmed at capture start.",
    }
    partition_plan = json.loads(
        (root / "verification" / f"{a.case}-partitions.json").read_text()
    )
    output["partition_plan"] = partition_plan
    output["conservative_50ms_gate"] = duration(conservative) > 50_000_000
    output["reference_only"] = a.reference
    assert a.reference or duration(conservative) > 50_000_000, (
        "No substantial overlap under shared server residence"
    )
(root / "analysis/static-concurrency-summary.json").write_text(
    json.dumps(output, indent=2)
)
(root / "analysis/shared-server-residence.json").write_text(
    json.dumps(
        {
            "resident": resident,
            "safe_overlap": safe,
            "t0": kernels["batch_t0_ns"],
            "window": [lo, hi],
        }
    )
)
print(json.dumps({k: v for k, v in output.items() if k != "model_trace"}, indent=2))
