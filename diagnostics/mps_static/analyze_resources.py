"""Measured-window host/device-wide1Hz resource summaries; missing GPU memory stays null."""

import argparse
import json
from pathlib import Path
import statistics

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
r = a.root
samples = [
    json.loads(line)
    for line in (r / "verification/host-samples.jsonl").read_text().splitlines()
]


def gpu(v, i):
    try:
        return float(v.get("gpu_query_csv", "").split(",")[i].strip())
    except (ValueError, IndexError):
        return None


def stats(vals):
    vals = [v for v in vals if v is not None]
    return (
        {"mean": statistics.mean(vals), "min": min(vals), "max": max(vals)}
        if vals
        else None
    )


out = []
for e in json.loads((r / "schedule.json").read_text()):
    folder = r / "results" / e["label"]
    m = json.loads((folder / "manifest.json").read_text())
    s = json.loads((folder / "summary.json").read_text())
    lo = m["batch_t0_perf_ns"]
    hi = lo + s["overall_completion_ms"] * 1e6
    rows = [v for v in samples if lo <= v["monotonic_ns"] <= hi]
    out.append(
        {
            "trial": e["label"],
            "condition": e["condition"],
            "samples": len(rows),
            "cpu_percent": stats([v.get("host_cpu_percent") for v in rows]),
            "gpu_util_reported": stats([gpu(v, 0) for v in rows]),
            "gpu_temperature_c": stats([gpu(v, 1) for v in rows]),
            "reported_power_w": stats([gpu(v, 2) for v in rows]),
            "host_memory_used_gib": stats(
                [
                    (v["memory_total_bytes"] - v["memory_available_bytes"]) / 2**30
                    for v in rows
                ]
            ),
            "gpu_memory_used_reported": stats([gpu(v, 3) for v in rows]),
        }
    )
(r / "analysis/resources.json").write_text(
    json.dumps(
        {
            "note": "Host/device-wide1Hzsampling;notper-modelVRAM/SM-active;N/Akeptnull;measuredwindowsOnly",
            "trials": out,
        },
        indent=2,
    )
)
print(r / "analysis/resources.json")
