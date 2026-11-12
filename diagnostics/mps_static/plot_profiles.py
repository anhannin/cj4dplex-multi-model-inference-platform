"""Exact aligned diagnostic micro-timelines, separate from timed performance results."""

import gzip
import json
from pathlib import Path
import sys
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kernel_overlap"))
from analyze_reports import clip

fig, axes = plt.subplots(2, 1, figsize=(14, 7))
for ax, name, case, title in [
    (
        axes[0],
        "mps-only",
        "native-mps-only",
        "Reference: MPS shared, full48 available to each process",
    ),
    (
        axes[1],
        "static-q8-y40",
        "native-static-q8-y40",
        "Selected: MPS static Qwen8 / YOLO40, no Green Context",
    ),
]:
    root = Path("results/static-profile") / ("20261110-final-" + name)
    with gzip.open(root / "analysis" / f"{case}-intervals.json.gz", "rt") as f:
        data = json.load(f)
    residence = json.loads((root / "analysis/shared-server-residence.json").read_text())
    t0 = data["batch_t0_ns"]
    start = t0 + 1_000_000_000
    end = start + 30_000_000
    tracks = [
        ("Qwen kernel elapsed spans", data["qwen"], "#6b9acb"),
        ("YOLO kernel elapsed spans", data["yolo"], "#f0b46e"),
        ("MPS-associated context", residence["resident"], "#555555"),
        ("Kernel overlap, no switch", residence["safe_overlap"], "#238b45"),
    ]
    for i, (label, vals, color) in enumerate(tracks):
        ax.broken_barh(
            [((a - start) / 1e6, (b - a) / 1e6) for a, b in clip(vals, start, end)],
            (i - 0.32, 0.64),
            facecolors=color,
        )
    ax.set_yticks(range(4))
    ax.set_yticklabels([v[0] for v in tracks])
    ax.set_ylim(3.6, -0.6)
    ax.set_xlim(0, 30)
    ax.set_xlabel("Milliseconds from each burst t0 + 1000ms")
    ax.set_title(title)
    ax.grid(axis="x", alpha=0.25)
fig.suptitle(
    "Actual Qwen9B / YOLO26l diagnostic kernel spans and hardware-context scheduling\nElapsed spans are not pure SM-active instruction time; no profiler timings used in performance ranking",
    fontsize=11,
)
fig.tight_layout(rect=(0, 0, 1, 0.93))
out = Path("results/static-eval/20261110-v1/plots/diagnostic-timelines.png")
fig.savefig(out, dpi=170)
print(out)
