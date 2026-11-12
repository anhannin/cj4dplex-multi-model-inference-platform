"""Parse actual counter values; absent DRAM metrics remain absent, not zero."""

import argparse
import csv
import io
import json
import math
from pathlib import Path


def metric_number(value):
    try:
        result = float(value.replace(",", ""))
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, AttributeError):
        return None


def parse_rows(rows):
    kernels = {}
    for row in rows:
        key = row.get("ID", "")
        if not key.isdigit():
            continue
        entry = kernels.setdefault(
            key,
            {"id": int(key), "kernel": row["Kernel Name"], "metrics": {}, "rules": []},
        )
        if row.get("Metric Name"):
            name = row["Metric Name"]
            value = metric_number(row.get("Metric Value"))
            entry["metrics"][name] = {
                "value": value,
                "unit": row.get("Metric Unit"),
                "raw": row.get("Metric Value"),
                "section": row.get("Section Name"),
            }
        if row.get("Rule Name"):
            entry["rules"].append(
                {"name": row["Rule Name"], "text": row.get("Rule Description")}
            )
    return [kernels[k] for k in sorted(kernels, key=int)]


def select_linear_targets(names):
    names = list(names)
    for name in names:
        if name.endswith(".mlp.up_proj"):
            down = name.rsplit(".", 1)[0] + ".down_proj"
            if down in names:
                return [name, down]
    raise ValueError("No matching up/down pair found")


def derive_raw_stalls(raw):
    base = metric_number(raw.get("smsp__average_warp_latency_per_inst_issued.ratio"))
    result = {}
    for name in ("long_scoreboard", "lg_throttle"):
        metric = "smsp__average_warps_issue_stalled_" + name + "_per_issue_active.ratio"
        value = metric_number(raw.get(metric))
        result[name + "_contribution_pct"] = (
            value / base * 100 if base and value is not None else None
        )
    result["interpretation"] = (
        "contribution to average warp issue interval, not program wall time"
    )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    text = a.input.read_text()
    start = text.index('"ID"')
    rows = list(csv.DictReader(io.StringIO(text[start:])))
    result = {
        "scope": "kernel replay diagnostic, not serving latency baseline",
        "kernels": parse_rows(rows),
    }
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    for entry in result["kernels"]:
        names = (
            "Duration",
            "Compute (SM) Throughput",
            "Memory Throughput",
            "DRAM Throughput",
            "Achieved Occupancy",
            "Theoretical Occupancy",
        )
        print(entry["id"], {k: entry["metrics"].get(k, {}).get("raw") for k in names})


if __name__ == "__main__":
    main()
