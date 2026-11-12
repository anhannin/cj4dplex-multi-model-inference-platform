"""CPU-only batch completion and non-overlapping host components, GPU shown separately."""

import argparse
import json
from pathlib import Path
import statistics


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    data = json.loads((a.root / "analysis/summary.json").read_text())
    points = sorted(
        data["comparison"],
        key=lambda r: -1
        if r["label"] == "default"
        else int(r["label"].split("-")[0][1:]),
    )
    labels = [
        "No Green\n48 / 48"
        if r["label"] == "default"
        else r["label"].replace("q", "Q").replace("-y", " / Y")
        for r in points
    ]
    x = np.arange(len(points))
    plots = a.root / "plots"
    plots.mkdir(exist_ok=True)
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "font.size": 10, "savefig.dpi": 170}
    )
    fig, axes = plt.subplots(1, 3, figsize=(17, 5))
    for ax, key, title in (
        (axes[0], "total_ms", "All310 jobs: batch makespan"),
        (axes[1], "yolo_ms", "YOLO300: batch completion"),
        (axes[2], "qwen_ms", "Qwen10: batch completion"),
    ):
        mean = [r[key]["mean"] / 1000 for r in points]
        std = [r[key]["std"] / 1000 for r in points]
        ax.bar(
            x, mean, yerr=std, capsize=3, color=["#777777"] + ["#2468b4"] * (len(x) - 1)
        )
        for i, v in enumerate(mean):
            ax.text(i, v + max(mean) * 0.025, f"{v:.2f}", ha="center", fontsize=9)
        ax.set_xticks(x, labels, rotation=15)
        ax.set_ylabel("Seconds from common barrier t0")
        ax.set_title(title)
        ax.set_ylim(0, max(mean) * 1.18)
        ax.grid(axis="y", alpha=0.25)
    fig.suptitle(
        "Fixed simultaneous burst: Qwen10 + YOLO300, Green before/after", fontsize=14
    )
    fig.text(
        0.5,
        0.01,
        "3 measured bursts/config; noGreen pools3 before+3 after (drift reported). Same buffers/instrumentation. Mean +/-1SD; no solo trials. Qwen512/128, bus640,batch1.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.06, 1, 0.95])
    for ext in ("png", "svg"):
        fig.savefig(plots / ("burst-completion." + ext))
    plt.close(fig)
    colors = ["#dda447", "#2468b4", "#8cb2d7", "#aaaaaa"]
    keys = [
        "app_queue_ms",
        "model_pipeline_ms",
        "server_nonpipeline_ms",
        "transport_client_residual_ms",
    ]
    names = [
        "Application queue",
        "Model pipeline host wall",
        "Server other",
        "Transport/client residual",
    ]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, model in zip(axes, ("qwen", "yolo")):
        base = np.zeros(len(points))
        model_values = []
        for point in points:
            group = [
                t
                for t in data["trials"]
                if (
                    t["trial"].startswith("default-")
                    if point["label"] == "default"
                    else t["trial"].startswith(point["label"] + "-r")
                )
            ]
            model_values.append(
                {
                    key: statistics.mean(
                        t["models"][model]["metrics"][key]["mean"] for t in group
                    )
                    / 1000
                    for key in keys
                }
            )
        for key, name, color in zip(keys, names, colors):
            values = np.array([v[key] for v in model_values])
            ax.bar(x, values, bottom=base, label=name, color=color)
            base += values
        ax.set_xticks(x, labels, rotation=15)
        ax.set_ylabel("Mean per-request E2E (s)")
        ax.set_title(model.upper() + ": additive host-stage accounting")
        ax.grid(axis="y", alpha=0.25)
        ax.legend(fontsize=7)
    fig.suptitle(
        "Queue vs pipeline: GPU event spans are nested submetrics, NOT added twice",
        fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    for ext in ("png", "svg"):
        fig.savefig(plots / ("burst-components." + ext))
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, model in zip(axes, ("qwen", "yolo")):
        means = []
        for point in points:
            group = [
                t
                for t in data["trials"]
                if (
                    t["trial"].startswith("default-")
                    if point["label"] == "default"
                    else t["trial"].startswith(point["label"] + "-r")
                )
            ]
            means.append(
                statistics.mean(
                    t["models"][model]["metrics"]["gpu_forward_span_ms"]["mean"]
                    for t in group
                )
            )
        scale = 1000 if model == "qwen" else 1
        ax.plot(x, [v / scale for v in means], marker="o", color="#2468b4")
        ax.set_xticks(x, labels, rotation=15)
        ax.set_title(model.upper() + " selected-stream native forward span")
        ax.set_ylabel(
            "Device timeline " + ("s/request" if model == "qwen" else "ms/request")
        )
        ax.grid(alpha=0.25)
    fig.suptitle(
        "CUDA-event spans: not pure kernel busy time; application queue excluded",
        fontsize=13,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    for ext in ("png", "svg"):
        fig.savefig(plots / ("burst-gpu-forward." + ext))
    plt.close(fig)


if __name__ == "__main__":
    main()
