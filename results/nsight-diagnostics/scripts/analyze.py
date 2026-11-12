"""Offline, non-additive timing analysis of CUDA activity SQLite reports."""

import argparse
import csv
import json
from pathlib import Path
import sqlite3
from benchmark.aggregate_latency import stats


def union_ns(intervals):
    intervals = sorted(intervals)
    if not intervals:
        return 0
    start, end = intervals[0]
    total = 0
    for left, right in intervals[1:]:
        if left <= end:
            end = max(end, right)
        else:
            total += end - start
            start, end = left, right
    return total + end - start


def range_coverage(start, end, intervals):
    clipped = [
        (max(start, a), min(end, b)) for a, b in intervals if a < end and b > start
    ]
    union = union_ns(clipped)
    return {"kernel_union_ns": union, "non_kernel_coverage_ns": end - start - union}


def delay_metrics(kernels, apis):
    launches = {}
    for api in apis:
        if "Launch" not in api["name"]:
            continue
        cid = api.get("correlationId")
        # Prefer driver-level launch when both API layers expose the same ID.
        if cid not in launches or api.get("api_kind") == "driver":
            launches[cid] = api
    signed = []
    submit = []
    api_times = []
    early = 0
    for k in kernels:
        a = launches.get(k.get("correlationId"))
        if a is None:
            continue
        signed.append((k["start"] - a["end"]) / 1000)
        submit.append((k["start"] - a["start"]) / 1000)
        api_times.append((a["end"] - a["start"]) / 1000)
        if k["start"] < a["end"]:
            early += 1
    return {
        "matched_kernel_count": len(signed),
        "unmatched_kernel_count": len(kernels) - len(signed),
        "kernel_started_before_api_return": early,
        "post_return_signed_us": stats(signed),
        "positive_post_return_us": stats([v for v in signed if v >= 0]),
        "api_entry_to_kernel_start_us": stats(submit),
        "matched_launch_api_us": stats(api_times),
    }


def table_rows(db, name):
    names = {
        r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if name not in names:
        return []
    return [dict(row) for row in db.execute('SELECT * FROM "' + name + '"')]


def report(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    strings = {row["id"]: row["value"] for row in table_rows(db, "StringIds")}
    kernels = table_rows(db, "CUPTI_ACTIVITY_KIND_KERNEL")
    for k in kernels:
        k["name"] = strings.get(
            k.get("demangledName"), strings.get(k.get("shortName"), "unknown")
        )
    apis = []
    for table, kind in (
        ("CUPTI_ACTIVITY_KIND_RUNTIME", "runtime"),
        ("CUPTI_ACTIVITY_KIND_DRIVER", "driver"),
    ):
        for a in table_rows(db, table):
            a["name"] = strings.get(a.get("nameId"), "unknown")
            a["api_kind"] = kind
            apis.append(a)
    nvtx = table_rows(db, "NVTX_EVENTS")
    ranges = []
    for r in nvtx:
        name = r.get("text") or strings.get(r.get("textId"), "")
        if name.startswith("phase:") or name in ("qwen.generate", "yolo.predict"):
            if r.get("end") is not None and r["end"] >= r["start"]:
                ranges.append(
                    {
                        "name": name,
                        "start": r["start"],
                        "end": r["end"],
                        "duration_ms": (r["end"] - r["start"]) / 1e6,
                    }
                )
    groups = {}
    for k in kernels:
        groups.setdefault(k["name"], []).append((k["end"] - k["start"]) / 1000)
    grouped = [
        {
            "name": name,
            "calls": len(values),
            "total_ms": sum(values) / 1000,
            **{k + "_us": v for k, v in stats(values).items() if k != "n"},
        }
        for name, values in groups.items()
    ]
    grouped.sort(key=lambda r: r["total_ms"], reverse=True)
    api_groups = {}
    for a in apis:
        api_groups.setdefault(a["api_kind"] + ":" + a["name"], []).append(
            (a["end"] - a["start"]) / 1000
        )
    api_summary = [
        {
            "name": name,
            "calls": len(values),
            "total_ms": sum(values) / 1000,
            "mean_us": sum(values) / len(values),
            "p95_us": stats(values)["p95"],
        }
        for name, values in api_groups.items()
    ]
    api_summary.sort(key=lambda r: r["total_ms"], reverse=True)
    mem = table_rows(db, "CUPTI_ACTIVITY_KIND_MEMCPY")
    os_rows = table_rows(db, "OSRT_API")
    os_groups = {}
    for a in os_rows:
        os_groups.setdefault(strings.get(a.get("nameId"), "unknown"), []).append(
            (a["end"] - a["start"]) / 1000
        )
    os_summary = [
        {
            "name": n,
            "calls": len(v),
            "total_ms": sum(v) / 1000,
            "mean_us": sum(v) / len(v),
        }
        for n, v in os_groups.items()
    ]
    os_summary.sort(key=lambda r: r["total_ms"], reverse=True)
    intervals = [(k["start"], k["end"]) for k in kernels]
    for r in ranges:
        r.update(range_coverage(r["start"], r["end"], intervals))
    phase_ranges = [r for r in ranges if r["name"].startswith("phase:")]
    duration = (
        phase_ranges[0]["end"] - phase_ranges[0]["start"] if phase_ranges else None
    )
    result = {
        "file": str(path),
        "kernel_count": len(kernels),
        "kernel_elapsed_sum_ms": sum(b - a for a, b in intervals) / 1e6,
        "kernel_elapsed_union_ms": union_ns(intervals) / 1e6,
        "capture_phase_ms": duration / 1e6 if duration is not None else None,
        "kernel_union_fraction_of_phase": union_ns(intervals) / duration
        if duration
        else None,
        "kernel_duration_us": stats([(b - a) / 1000 for a, b in intervals]),
        "launch_delays": delay_metrics(kernels, apis),
        "top_kernels": grouped,
        "top_cuda_apis": api_summary,
        "top_osrt_apis": os_summary,
        "nvtx_ranges": ranges,
        "memcpy_count": len(mem),
        "memcpy_total_bytes": sum(r.get("bytes", 0) for r in mem),
        "memcpy_elapsed_sum_ms": sum(r["end"] - r["start"] for r in mem) / 1e6,
    }
    db.close()
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    a = p.parse_args()
    output = {}
    for model in ("qwen", "yolo"):
        output[model] = {}
        for phase in ("qwen-only", "yolo-only", "concurrent"):
            path = a.root / "reports" / model / (phase + ".sqlite")
            summary = report(path)
            output[model][phase] = summary
            file = a.root / (model + "-" + phase + "-kernels.csv")
            with file.open("w") as stream:
                rows = summary["top_kernels"]
                if rows:
                    w = csv.DictWriter(stream, fieldnames=list(rows[0]))
                    w.writeheader()
                    w.writerows(rows)
    (a.root / "analysis.json").write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                m: {
                    p: {
                        "kernels": s["kernel_count"],
                        "gpu_union_ms": s["kernel_elapsed_union_ms"],
                        "phase_ms": s["capture_phase_ms"],
                    }
                    for p, s in phases.items()
                }
                for m, phases in output.items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
