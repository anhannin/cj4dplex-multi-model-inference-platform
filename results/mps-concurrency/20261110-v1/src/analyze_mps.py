"""Analyze actual models under MPS, not kernel spans under switching client contexts."""

import argparse
import gzip
import json
from pathlib import Path
import sqlite3
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kernel_overlap"))
from analysis import duration, fit_clock, intersect
from analyze_reports import case_analysis, clip, text_events
from scheduler_analysis import residencies

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
p.add_argument("--case", default="mps-green-q16-y32-r1")
a = p.parse_args()
root = a.root
model = case_analysis(root, a.case, True)
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
        (root / "verification" / f"{a.case}-burst-mps-membership.json").read_text()
    )
    server = int(membership["servers"].strip())
    clients = [int(v) for v in membership["clients"][str(server)].split()]
    assert len(set(clients)) == 2
    resident = clip(
        [(start, end) for start, end, c, pid in intervals if pid == server], lo, hi
    )
    overlap = kernels["intersection"]
    guarded = [
        (start + 100000, end - 100000)
        for start, end in resident
        if end - start > 200000
    ]
    safe = intersect(overlap, guarded)
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
        "context_pids": sorted(
            {(pid >> 24) & 0xFFFFFF for tag, c, t, pid, seq in rows}
        ),
        "mps_server_resident_ms": duration(resident) / 1e6,
        "cross_model_kernel_overlap_in_shared_server_residence_ms": duration(
            intersect(overlap, resident)
        )
        / 1e6,
        "overlap_away_from_context_transitions_100us_ms": duration(safe) / 1e6,
        "device_metrics": metrics,
        "note": "Kernel start/end overlap inside shared MPS GPU-context residence, with verified two actual-model clients. Aggregate metrics are not attributed to individual processes. No claim of globally exclusive 16/32 partitions from client-local SM IDs.",
    }
    assert duration(safe) > 50_000_000, (
        "No substantial overlap under shared server residence"
    )
(root / "analysis/mps-concurrency-summary.json").write_text(
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
