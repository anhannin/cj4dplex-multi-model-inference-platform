"""Display exact 30ms micro-timelines before/after MPS, no occupancy inference."""

import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kernel_overlap"))
from analyze_reports import clip
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

base = Path("results/kernel-overlap/20261110-v1")
root = Path("results/mps-concurrency/20261110-v1")
old = json.loads((base / "analysis/scheduler-residencies.json").read_text())
new = json.loads((root / "analysis/shared-server-residence.json").read_text())
fig, axes = plt.subplots(2, 1, figsize=(13, 7))
for ax, folder, case, res, title in [
    (axes[0], base, "q16-y32-ctxsw2", old, "Before: two processes, Green16/32, no MPS"),
    (
        axes[1],
        root,
        "mps-green-q16-y32-r1",
        new,
        "After: two processes, Green16/32 + MPS",
    ),
]:
    with gzip.open(folder / "analysis" / f"{case}-intervals.json.gz", "rt") as f:
        data = json.load(f)
    t0 = data["batch_t0_ns"]
    start = t0 + 1_000_000_000
    end = start + 30_000_000
    tracks = [
        ("Qwen kernel spans", data["qwen"], "#699bd0"),
        ("YOLO kernel spans", data["yolo"], "#f0b66e"),
    ]
    if folder == base:
        tracks += [
            ("Qwen context", res["qwen"], "#225ea8"),
            ("YOLO context", res["yolo"], "#d95f02"),
        ]
    else:
        tracks += [
            ("MPS-associated context", res["resident"], "#555555"),
            ("Kernel overlap, no switch", res["safe_overlap"], "#238b45"),
        ]
    for i, (label, intervals, color) in enumerate(tracks):
        bars = [
            ((a - start) / 1e6, (b - a) / 1e6) for a, b in clip(intervals, start, end)
        ]
        ax.broken_barh(bars, (i - 0.32, 0.64), facecolors=color)
    ax.set_yticks(range(4))
    ax.set_yticklabels([v[0] for v in tracks])
    ax.set_ylim(3.6, -0.6)
    ax.set_xlim(0, 30)
    ax.set_title(title)
    ax.set_xlabel("ms from each burst t0 + 1000ms")
    ax.grid(axis="x", alpha=0.25)
fig.suptitle(
    "Actual Qwen9B / YOLO26l: distinguish elapsed kernel spans from context scheduling",
    fontsize=12,
)
fig.tight_layout(rect=(0, 0, 1, 0.96))
(root / "plots").mkdir(exist_ok=True)
fig.savefig(root / "plots/before-after-mps.png", dpi=170)
