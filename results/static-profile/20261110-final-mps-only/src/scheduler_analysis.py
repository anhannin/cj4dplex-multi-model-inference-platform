"""Distinguish kernel elapsed spans from driver context residence."""

import argparse
import gzip
import json
from pathlib import Path
import sqlite3
import statistics

from analysis import duration, fit_clock, intersect
from analyze_reports import case_analysis, clip, text_events


def residencies(rows):
    intervals = []
    active = None
    for tag, context, stamp, pid in rows:
        if tag == 8:
            assert active is None, ("Restore without save", active)
            active = (stamp, context, pid)
        elif tag == 7:
            assert active is not None and active[1:] == (context, pid)
            assert stamp >= active[0]
            intervals.append((active[0], stamp, context, pid))
            active = None
        else:
            raise ValueError(f"Unexpected context-switch tag: {tag}")
    return intervals, active


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--plot-only", action="store_true")
    args = parser.parse_args()
    if args.plot_only:
        plot(args.root)
        return
    root = args.root
    case = "q16-y32-ctxsw2"
    model = case_analysis(root, case, True)
    with gzip.open(root / "analysis" / f"{case}-intervals.json.gz", "rt") as f:
        kernels = json.load(f)
    lo, hi = kernels["window_ns"]
    t0 = kernels["batch_t0_ns"]
    folder = root / "validation" / case / "scheduler"
    with sqlite3.connect(folder / "trace.sqlite") as conn:
        marks = {
            name: a
            for a, b, name in text_events(conn)
            if name.startswith("clock:scheduler:")
        }
        records = [
            json.loads(line)
            for line in (folder / "clocks.jsonl").read_text().splitlines()
        ]
        assert all(r["name"] in marks for r in records)
        clock = fit_clock([{**r, "trace_ns": marks[r["name"]]} for r in records])
        mapping = clock["map"]
        rows = conn.execute(
            "SELECT tag,contextId,timestamp,globalPid,seqNo FROM GPU_CONTEXT_SWITCH_EVENTS ORDER BY timestamp"
        ).fetchall()
        assert all(b[4] == a[4] + 1 for a, b in zip(rows, rows[1:])), "Sequence gap"
        intervals, tail = residencies(
            [
                (tag, ctx, mapping(ts), (pid >> 24) & 0xFFFFFF)
                for tag, ctx, ts, pid, seq in rows
            ]
        )
        # Verified against own host Python process command lines, not container CUPTI PID.
        pids = {"qwen": 875217, "yolo": 875036}
        selected = {
            name: clip([(a, b) for a, b, ctx, pid in intervals if pid == p], lo, hi)
            for name, p in pids.items()
        }
        assert tail is None or tail[0] >= hi, (
            "Unclosed residence intersects analysis window"
        )
        other = clip(
            [(a, b) for a, b, ctx, pid in intervals if pid not in pids.values()], lo, hi
        )
        metrics = {}
        for metric in (6, 7, 8, 9, 16):
            values = [
                v
                for ts, v in conn.execute(
                    "SELECT timestamp,value FROM GPU_METRICS WHERE metricId=?",
                    (metric,),
                )
                if lo <= mapping(ts) < hi
            ]
            assert values and min(values) >= 0 and max(values) <= 100
            metrics[str(metric)] = {
                "samples": len(values),
                "mean_percent": statistics.mean(values),
                "max_percent": max(values),
            }
        report = {
            "case": case,
            "common_window_ms": (hi - lo) / 1e6,
            "host_pid_mapping": pids,
            "context_events": len(rows),
            "internal_sequence_gaps": 0,
            "clock": {k: v for k, v in clock.items() if k != "map"},
            "unclosed_tail": tail,
            "residence_ms": {name: duration(v) / 1e6 for name, v in selected.items()},
            "residence_slices": {name: len(v) for name, v in selected.items()},
            "median_residence_ms": {
                name: statistics.median([b - a for a, b in v]) / 1e6
                for name, v in selected.items()
            },
            "cross_process_residence_overlap_ms": duration(
                intersect(selected["qwen"], selected["yolo"])
            )
            / 1e6,
            "other_context_residence_ms": duration(other) / 1e6,
            "kernel_span_overlap_ms": model["cross_kernel_overlap_ms"],
            "qwen_kernel_spans_during_yolo_residence_ms": duration(
                intersect(kernels["qwen"], selected["yolo"])
            )
            / 1e6,
            "gpu_metrics_device_level": metrics,
            "interpretation": "RESTORE_START to SAVE_END residence intervals are alternating. Kernel elapsed spans include descheduled time; they do not prove simultaneous SM execution. Finite profiled two-process capture only.",
        }
    (root / "analysis/scheduler-summary.json").write_text(json.dumps(report, indent=2))
    (root / "analysis/scheduler-residencies.json").write_text(
        json.dumps({"t0": t0, "window": [lo, hi], **selected, "other": other})
    )
    print(json.dumps(report, indent=2))


def plot(root):
    data = json.loads((root / "analysis/scheduler-residencies.json").read_text())
    selected = {k: data[k] for k in ("qwen", "yolo")}
    lo, hi = data["window"]
    t0 = data["t0"]
    with gzip.open(root / "analysis/q16-y32-ctxsw2-intervals.json.gz", "rt") as f:
        kernels = json.load(f)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Exact 30ms slice with both contexts active, no binning.
    start = next(a for a, b in selected["yolo"] if a > lo + 1_000_000_000)
    end = start + 30_000_000
    fig, ax = plt.subplots(figsize=(13, 4))
    for row, (label, values, color) in enumerate(
        [
            ("Qwen kernel elapsed spans", kernels["qwen"], "#7aa6d8"),
            ("YOLO kernel elapsed spans", kernels["yolo"], "#f0b66e"),
            ("Qwen context residence", selected["qwen"], "#225ea8"),
            ("YOLO context residence", selected["yolo"], "#d95f02"),
        ]
    ):
        bars = [((a - start) / 1e6, (b - a) / 1e6) for a, b in clip(values, start, end)]
        ax.broken_barh(bars, (row - 0.32, 0.64), facecolors=color)
    ax.set_yticks(range(4))
    ax.set_yticklabels(
        ["Qwen kernel spans", "YOLO kernel spans", "Qwen context", "YOLO context"]
    )
    ax.set_xlim(0, 30)
    ax.set_xlabel(f"Milliseconds from burst t0 + {(start - t0) / 1e6:.3f} ms")
    ax.set_title(
        "Green Qwen16 / YOLO32: overlapping elapsed spans, alternating GPU contexts"
    )
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    (root / "plots").mkdir(exist_ok=True)
    fig.savefig(root / "plots/context-residence-zoom.png", dpi=170)


if __name__ == "__main__":
    main()
