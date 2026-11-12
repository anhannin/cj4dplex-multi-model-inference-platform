"""Offline plots: actual five bursts, non-overlapping E2E parts, nested GPU spans."""

import argparse
import json
from pathlib import Path
import statistics
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
root = a.root
summary = json.loads((root / "analysis/summary.json").read_text())
order = ["control", "mps-only"] + [
    f"static-q{q}-y{48 - q}" for q in (8, 16, 24, 32, 40)
]
by = {r["label"]: r for r in summary["conditions"]}
labels = ["No MPS", "MPS shared"] + [
    f"Static {q}/{48 - q}" for q in (8, 16, 24, 32, 40)
]
x = np.arange(7)
colors = ["#8a8a8a", "#4c78a8"] + ["#54a24b"] * 5
out = root / "plots"
out.mkdir(exist_ok=True)
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "savefig.dpi": 170})
fig, axes = plt.subplots(1, 2, figsize=(14, 4.8))
for ax, key, title in [
    (axes[0], "total_ms", "All 310 results received"),
    (axes[1], "yolo_ms", "All 300 YOLO results received"),
]:
    means = [by[c][key]["mean"] / 1000 for c in order]
    errs = [by[c][key]["std"] / 1000 for c in order]
    ax.bar(x, means, yerr=errs, color=colors, alpha=0.8, capsize=4)
    for i, c in enumerate(order):
        values = [
            (
                t["completion"]["overall_completion_ms"]
                if key == "total_ms"
                else t["completion"]["model_completion_ms"]["yolo"]
            )
            / 1000
            for t in summary["trials"]
            if t["condition"] == c
        ]
        ax.scatter(
            i + np.linspace(-0.12, 0.12, 5), values, color="black", s=13, zorder=4
        )
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("Seconds from common burst release")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.2)
fig.suptitle(
    "Simultaneous Qwen10 / YOLO300, native MPS STATIC (Qwen SM / YOLO SM)\nMean +/- population SD across 5 bursts; black dots = individual bursts",
    fontsize=11,
)
fig.tight_layout(rect=(0, 0, 1, 0.89))
fig.savefig(out / "batch-completion.png")
plt.close(fig)
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
keys = [
    ("app_queue_ms", "Application FIFO"),
    ("model_pipeline_ms", "Model pipeline"),
    ("server_nonpipeline_ms", "Other server processing"),
    ("transport_client_residual_ms", "Transport/client/publication residual"),
]
for ax, m in zip(axes, ("qwen", "yolo")):
    bottom = np.zeros(7)
    for k, label in keys:
        vals = np.array(
            [by[c]["models"][m]["pooled_descriptive"][k]["mean"] / 1000 for c in order]
        )
        ax.bar(x, vals, bottom=bottom, label=label)
        bottom += vals
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylabel("Mean request E2E seconds")
    ax.set_title(m.upper())
    ax.grid(axis="y", alpha=0.2)
axes[1].legend(fontsize=8)
fig.suptitle(
    "Non-overlapping host E2E accounting; GPU-event spans are NOT added", fontsize=12
)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(out / "request-components.png")
plt.close(fig)
fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))
for ax, m, key, title in [
    (axes[0], "qwen", "gpu_prefill_span_ms", "Qwen prefill forward span"),
    (axes[1], "qwen", "gpu_decode_ms_per_token", "Qwen decode forward span / token"),
    (axes[2], "yolo", "gpu_forward_span_ms", "YOLO forward span"),
]:
    values = []
    errs = []
    for c in order:
        series = [
            t["models"][m]["metrics"][key]["mean"]
            for t in summary["trials"]
            if t["condition"] == c
        ]
        values.append(statistics.mean(series))
        errs.append(statistics.pstdev(series))
    ax.bar(x, values, yerr=errs, color=colors, capsize=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("CUDA-event elapsed ms")
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.2)
fig.suptitle(
    "Nested device-stream forward spans (include stalls/launch effects), not pure SM-active time",
    fontsize=11,
)
fig.tight_layout(rect=(0, 0, 1, 0.94))
fig.savefig(out / "gpu-forward-spans.png")
plt.close(fig)
print(out)
