"""Actual kernel interval overlap across independently anchored Nsight reports."""

import argparse
import gzip
import json
import math
from pathlib import Path
import sqlite3

from analysis import union, intersect, duration, overlap_bounds, fit_clock


def text_events(connection):
    return connection.execute(
        "SELECT n.start,n.end,COALESCE(n.text,s.value) FROM NVTX_EVENTS n LEFT JOIN StringIds s ON n.textId=s.id WHERE n.text IS NOT NULL OR n.textId IS NOT NULL"
    ).fetchall()


def parse_report(root, case, model, enabled):
    path = root / "validation" / case / model / "trace.sqlite"
    with sqlite3.connect(path) as c:
        events = text_events(c)
        marks = {
            text: start
            for start, end, text in events
            if text and text.startswith("clock:" + model + ":")
        }
        raw = [
            json.loads(line)
            for line in (root / "clocks" / f"{case}-{model}.jsonl")
            .read_text()
            .splitlines()
        ]
        missing = [r["name"] for r in raw if r["name"] not in marks]
        anchors = [
            {**r, "trace_ns": marks[r["name"]]} for r in raw if r["name"] in marks
        ]
        clock = fit_clock(anchors)
        mapping = clock["map"]
        # Keep raw UTC normalization-vs-wall differences as an independent alignment check.
        utc_offsets = [
            r["trace_ns"] - (r["wall_pre_ns"] + r["wall_post_ns"]) // 2 for r in anchors
        ]
        rois = sorted(
            (a, b, text)
            for a, b, text in events
            if text and text.startswith("request:" + model + ":") and b is not None
        )
        assert rois, "No actual model request scopes"
        values = c.execute(
            "SELECT start,end,greenContextId,streamId,globalPid,contextId FROM CUPTI_ACTIVITY_KIND_KERNEL ORDER BY start"
        ).fetchall()
        groups = {}
        streams = {}
        selected = []
        outside = 0
        crossings = 0
        i = 0
        for start, end, green, stream, pid, context in values:
            while i < len(rois) and start >= rois[i][1]:
                i += 1
            if i < len(rois) and start < rois[i][1] and end > rois[i][0]:
                if start < rois[i][0] or end > rois[i][1]:
                    crossings += 1
                    continue
                if enabled:
                    assert green not in (None, 0), ("Model escaped Green", model)
                else:
                    assert green in (None, 0), ("Control unexpectedly Green", model)
                groups[str(green)] = groups.get(str(green), 0) + 1
                key = (pid, context, green, stream)
                streams[key] = streams.get(key, 0) + 1
                selected.append((mapping(start), mapping(end)))
            else:
                outside += 1
        assert selected and crossings == 0, (model, len(selected), crossings)
        start_anchors = [r for r in anchors if r["tag"] == "capture-start"]
        stop_anchors = [r for r in anchors if r["tag"] == "capture-stop"]
        assert len(start_anchors) == len(stop_anchors) == 1
        cap_lo = (start_anchors[0]["pre_ns"] + start_anchors[0]["post_ns"]) // 2
        cap_hi = (stop_anchors[0]["pre_ns"] + stop_anchors[0]["post_ns"]) // 2
        info = {
            "model": model,
            "report": str(path),
            "clock": {k: v for k, v in clock.items() if k != "map"},
            "missing_anchor_count": len(missing),
            "utc_normalization_minus_wall_ns": {
                "min": min(utc_offsets),
                "max": max(utc_offsets),
            },
            "roi_count": len(rois),
            "kernels_in_rois": len(selected),
            "kernel_green_counts": groups,
            "kernel_stream_context_keys": [
                {
                    "globalPid": k[0],
                    "contextId": k[1],
                    "greenContextId": k[2],
                    "streamId": k[3],
                    "kernels": n,
                }
                for k, n in streams.items()
            ],
            "other_captured_kernels": outside,
            "boundary_crossings": crossings,
            "capture_monotonic_ns": [cap_lo, cap_hi],
            "model_host_rois": [(mapping(a), mapping(b), text) for a, b, text in rois],
        }
        info["clock"]["analysis_error_ns"] = math.ceil(
            clock["empirical_alignment_error_ns"] + 1000
        )
        return info, selected


def clip(intervals, lo, hi):
    return union([(max(a, lo), min(b, hi)) for a, b in intervals if b > lo and a < hi])


def case_analysis(root, case, enabled):
    q, qkernels = parse_report(root, case, "qwen", enabled)
    y, ykernels = parse_report(root, case, "yolo", enabled)
    manifest = json.loads(
        (root / "results" / (case + "-burst") / "manifest.json").read_text()
    )
    assert manifest["state"] == "PASS" and manifest["completed"] == 310
    t0 = manifest["batch_t0_perf_ns"]
    lo = max(t0, q["capture_monotonic_ns"][0], y["capture_monotonic_ns"][0])
    hi = min(q["capture_monotonic_ns"][1], y["capture_monotonic_ns"][1])
    assert hi > lo and hi - lo > 1_000_000_000
    qa, ya = clip(qkernels, lo, hi), clip(ykernels, lo, hi)
    overlaps = intersect(qa, ya)
    qe = q["clock"]["analysis_error_ns"]
    ye = y["clock"]["analysis_error_ns"]
    bounds = overlap_bounds(qa, ya, qe, ye)
    hostq = clip([(a, b) for a, b, _ in q["model_host_rois"]], lo, hi)
    hosty = clip([(a, b) for a, b, _ in y["model_host_rois"]], lo, hi)
    hostoverlap = duration(intersect(hostq, hosty))
    kernelunion = duration(union(qa + ya))
    result = {
        "case": case,
        "scope": "kernel execution intervals on common anchored host timeline; not per-SM instruction issue/occupancy guarantee",
        "common_window_from_batch_t0_ms": [(lo - t0) / 1e6, (hi - t0) / 1e6],
        "common_window_ms": (hi - lo) / 1e6,
        "qwen_kernel_union_ms": duration(qa) / 1e6,
        "yolo_kernel_union_ms": duration(ya) / 1e6,
        "cross_kernel_overlap_ms": duration(overlaps) / 1e6,
        "overlap_fraction_of_qwen": duration(overlaps) / duration(qa),
        "overlap_fraction_of_yolo": duration(overlaps) / duration(ya),
        "any_model_kernel_union_ms": kernelunion / 1e6,
        "no_model_kernel_interval_ms": (hi - lo - kernelunion) / 1e6,
        "host_model_call_overlap_ms": hostoverlap / 1e6,
        "empirical_alignment_tolerance_ns": {"qwen": qe, "yolo": ye},
        "overlap_tolerance_bounds_ms": {k: v / 1e6 for k, v in bounds.items()},
        "sensitivity": [],
        "reports": {"qwen": q, "yolo": y},
    }
    for extra in (1000, 10000, 100000):
        v = overlap_bounds(qa, ya, qe + extra, ye + extra)
        result["sensitivity"].append(
            {
                "extra_tolerance_ns": extra,
                **{k + "_ms": val / 1e6 for k, val in v.items()},
            }
        )
    with gzip.open(root / "analysis" / f"{case}-intervals.json.gz", "wt") as f:
        json.dump(
            {
                "batch_t0_ns": t0,
                "window_ns": [lo, hi],
                "qwen": qa,
                "yolo": ya,
                "intersection": overlaps,
                "qwen_host": hostq,
                "yolo_host": hosty,
            },
            f,
        )
    return result


def positive_analysis(root):
    with sqlite3.connect(root / "validation/positive/trace.sqlite") as c:
        events = text_events(c)
        intervals = {}
        expected_green = {}
        for label in (
            "control.serial0",
            "control.serial1",
            "control.parallel0",
            "control.parallel1",
        ):
            scopes = [(a, b) for a, b, t in events if t == label and b is not None]
            assert len(scopes) == 1
            lo, hi = scopes[0]
            rows = c.execute(
                "SELECT start,end,greenContextId FROM CUPTI_ACTIVITY_KIND_KERNEL WHERE start>=? AND end<=?",
                (lo, hi),
            ).fetchall()
            if label.startswith("control.serial"):
                assert len(rows) == 1 and rows[0][2] not in (None, 0)
                expected_green[label[-1]] = rows[0][2]
            else:
                # Two CPU NVTX scopes overlap; time containment alone also includes the OTHER thread's kernel.
                rows = [row for row in rows if row[2] == expected_green[label[-1]]]
                assert len(rows) == 1
            intervals[label] = [(a, b) for a, b, _ in rows]
        serial = duration(
            intersect(intervals["control.serial0"], intervals["control.serial1"])
        )
        parallel = duration(
            intersect(intervals["control.parallel0"], intervals["control.parallel1"])
        )
        assert serial == 0 and parallel > 50_000_000, (
            "Tool positive control failed",
            serial,
            parallel,
        )
        return {
            "state": "PASS",
            "serial_kernel_overlap_ms": serial / 1e6,
            "parallel_kernel_overlap_ms": parallel / 1e6,
            "scope": "synthetic method validation only; not model performance",
            "intervals_report_utc_ns": intervals,
        }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    status = json.loads((a.root / "verification/controller-status.json").read_text())
    assert status["state"] == "PASS" and status["restoration"] == "PASS"
    (a.root / "analysis").mkdir(exist_ok=True)
    out = {
        "positive_control": positive_analysis(a.root),
        "cases": [
            case_analysis(a.root, "q16-y32", True),
            case_analysis(a.root, "default", False),
        ],
    }
    (a.root / "analysis/summary.json").write_text(json.dumps(out, indent=2))
    for case in out["cases"]:
        print(
            case["case"],
            {
                k: case[k]
                for k in [
                    "common_window_ms",
                    "qwen_kernel_union_ms",
                    "yolo_kernel_union_ms",
                    "cross_kernel_overlap_ms",
                    "overlap_fraction_of_yolo",
                    "host_model_call_overlap_ms",
                    "empirical_alignment_tolerance_ns",
                    "overlap_tolerance_bounds_ms",
                ]
            },
        )
    print(out["positive_control"])


if __name__ == "__main__":
    main()
