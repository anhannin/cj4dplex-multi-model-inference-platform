"""CPU-only timeline from exact aligned kernel unions, overview binned ONLY for display."""

import argparse
import gzip
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    summary = json.loads((a.root / "analysis/summary.json").read_text())
    plots = a.root / "plots"
    plots.mkdir(exist_ok=True)
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "font.size": 10, "savefig.dpi": 170}
    )
    for case in summary["cases"]:
        name = case["case"]
        with gzip.open(a.root / "analysis" / f"{name}-intervals.json.gz", "rt") as f:
            data = json.load(f)
        lo, hi = data["window_ns"]
        t0 = data["batch_t0_ns"]
        step = 2_000_000
        edges = np.arange(lo, hi + step, step, dtype=np.int64)

        def occupancy(values):
            out = np.zeros(len(edges) - 1)
            for start, end in values:
                start = max(start, lo)
                end = min(end, hi)
                if end <= start:
                    continue
                first = int((start - lo) // step)
                last = int((end - lo - 1) // step)
                if first == last:
                    out[first] += (end - start) / step
                else:
                    out[first] += (edges[first + 1] - start) / step
                    out[last] += (end - edges[last]) / step
                    if last > first + 1:
                        out[first + 1 : last] += 1
            return np.clip(out, 0, 1)

        fig, axes = plt.subplots(5, 1, figsize=(15, 8), sharex=True)
        series = [
            ("Qwen host model calls", data["qwen_host"], "#777777"),
            ("YOLO host model calls", data["yolo_host"], "#777777"),
            ("Qwen GPU kernel intervals", data["qwen"], "#2468b4"),
            ("YOLO GPU kernel intervals", data["yolo"], "#e98429"),
            ("Kernel-interval intersection", data["intersection"], "#438c47"),
        ]
        times = (edges[:-1] - t0) / 1e9
        for ax, (label, values, color) in zip(axes, series):
            ax.fill_between(times, occupancy(values), step="post", color=color)
            ax.set_ylabel(label, fontsize=9)
            ax.set_ylim(0, 1.05)
            ax.set_yticks([0, 1])
            ax.grid(axis="x", alpha=0.25)
        axes[-1].set_xlabel(
            "Common host-monotonic seconds from burst t0 (clock-anchored)"
        )
        fig.suptitle(
            f"{name}: CPU calls vs GPU kernel intervals (2ms display bins)", fontsize=14
        )
        fig.text(
            0.5,
            0.015,
            f"Exact interval intersection={case['cross_kernel_overlap_ms']:.3f}ms; alignment empirical tolerances Q={case['empirical_alignment_tolerance_ns']['qwen'] / 1000:.1f}us/Y={case['empirical_alignment_tolerance_ns']['yolo'] / 1000:.1f}us. Kernel bars may include preemption/stalls: not SM instruction-issue proof.",
            ha="center",
            fontsize=8,
        )
        fig.tight_layout(rect=[0, 0.05, 1, 0.95])
        for ext in ("png", "svg"):
            fig.savefig(plots / f"{name}-timeline.{ext}")
        plt.close(fig)
        # A longest YOLO kernel union interval gives a nontrivial zoom; no smoothing/filtering of actual intervals.
        center = sum(max(data["yolo"], key=lambda v: v[1] - v[0])) // 2
        zl = max(lo, center - 2_000_000)
        zh = min(hi, center + 2_000_000)
        fig, ax = plt.subplots(figsize=(15, 4))
        for lane, key, color in [(1, "qwen", "#2468b4"), (0, "yolo", "#e98429")]:
            intervals = [
                ((max(s, zl) - zl) / 1e6, (min(e, zh) - max(s, zl)) / 1e6)
                for s, e in data[key]
                if e > zl and s < zh
            ]
            ax.broken_barh(intervals, (lane - 0.3, 0.6), facecolors=color)
        ax.set_yticks([0, 1], ["YOLO kernel intervals", "Qwen kernel intervals"])
        ax.set_xlim(0, (zh - zl) / 1e6)
        ax.set_xlabel("Milliseconds from zoom start")
        ax.set_title(
            f"{name}: exact kernel intervals near burst t={(zl - t0) / 1e9:.6f}s; preemption not removed"
        )
        ax.grid(axis="x", alpha=0.25)
        fig.tight_layout()
        for ext in ("png", "svg"):
            fig.savefig(plots / f"{name}-zoom.{ext}")
        plt.close(fig)
    pos = summary["positive_control"]["intervals_report_utc_ns"]
    base = min(x[0][0] for x in pos.values())
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.7))
    for ax, kind in zip(axes, ("serial", "parallel")):
        for index, color in [(0, "#2468b4"), (1, "#e98429")]:
            x, y = pos[f"control.{kind}{index}"][0]
            ax.broken_barh(
                [((x - base) / 1e6, (y - x) / 1e6)],
                (index - 0.3, 0.6),
                facecolors=color,
            )
        ax.set_yticks([0, 1], ["Green part0", "Green part1"])
        ax.set_xlabel("Report-relative ms")
        ax.set_title("Synthetic tool control: " + kind)
        ax.grid(axis="x", alpha=0.25)
    fig.suptitle("Method validation only, NOT real-model performance", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.9])
    for ext in ("png", "svg"):
        fig.savefig(plots / f"tool-controls.{ext}")
    plt.close(fig)


if __name__ == "__main__":
    main()
