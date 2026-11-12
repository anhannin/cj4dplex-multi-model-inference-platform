"""CPU-only visualization of paired ROS E2E and inference slowdown."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    a = parser.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    cases = json.loads((a.root / "analysis/comparison.json").read_text())
    cases = sorted(
        cases,
        key=lambda c: -1
        if c["label"] == "default"
        else int(c["label"].split("-")[0][1:]),
    )
    labels = [
        "Default\n48 / 48"
        if c["label"] == "default"
        else c["label"].replace("q", "Q").replace("-y", " / Y")
        for c in cases
    ]
    plots = a.root / "plots"
    plots.mkdir(exist_ok=True)
    plt.rcParams.update(
        {"font.family": "DejaVu Sans", "font.size": 10, "savefig.dpi": 170}
    )
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    positions = np.arange(len(cases))
    for ax, model, scale in ((axes[0], "qwen", 1000), (axes[1], "yolo", 1)):
        values = [
            c["models"][model]["metrics"]["request_e2e_ms"]["mean"] for c in cases
        ]
        solo = [r["solo"] / scale for r in values]
        both = [r["concurrent"] / scale for r in values]
        ax.bar(
            positions - 0.19,
            solo,
            width=0.38,
            label="Solo-active (other model resident, idle)",
            color="#92b7df",
        )
        ax.bar(positions + 0.19, both, width=0.38, label="Both active", color="#2468b4")
        for i, (x, y) in enumerate(zip(solo, both)):
            ax.text(
                i - 0.19,
                x + 0.01 * max(solo + both),
                f"{x:.2f}",
                ha="center",
                fontsize=8,
            )
            ax.text(
                i + 0.19,
                y + 0.01 * max(solo + both),
                f"{y:.2f}",
                ha="center",
                fontsize=8,
            )
        ax.set_ylabel("Mean ROS E2E (" + ("s" if model == "qwen" else "ms") + ")")
        ax.set_title(model.upper() + ": solo-active vs concurrent")
        ax.set_ylim(0, max(solo + both) * 1.2)
        ax.set_xticks(positions, labels, rotation=15)
        ax.grid(axis="y", alpha=0.25)
        ax.legend(fontsize=7)
    ax = axes[2]
    for model, color in [("qwen", "#2468b4"), ("yolo", "#e98429")]:
        ratios = [
            c["models"][model]["metrics"]["request_e2e_ms"]["mean"]["ratio"]
            for c in cases
        ]
        ax.plot(positions, ratios, marker="o", label=model.upper(), color=color)
    ax.axhspan(
        0.95,
        1.05,
        alpha=0.12,
        color="green",
        label="Descriptive +/-5% band (not equivalence test)",
    )
    ax.axhline(1, color="gray", linestyle="--")
    ax.set_ylabel("Concurrent / solo-active mean E2E")
    ax.set_title("Interference: 1.0 means unchanged mean")
    ax.set_xticks(positions, labels, rotation=15)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=7)
    fig.suptitle(
        "Actual two-Pod Green Context SM combinations: ROS request E2E", fontsize=15
    )
    fig.text(
        0.5,
        0.015,
        "Fixed512 input /128 output tokens, bus.jpg640,batch1;C1/model adaptive closed-loop;Qwen N10/phase;MPS/TRT/DDS tuning OFF. Similar E2E does not prove GPU kernel overlap.",
        ha="center",
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.07, 1, 0.94])
    for suffix in ("png", "svg"):
        fig.savefig(plots / ("green-e2e-combinations." + suffix))
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, model, primary in (
        (axes[0], "qwen", "generate_wall_ms"),
        (axes[1], "yolo", "yolo_inference_ms"),
    ):
        for metric, label, color in [
            ("request_e2e_ms", "ROS E2E", "#2468b4"),
            (primary, "Generate/inference stage", "#e98429"),
        ]:
            ax.plot(
                positions,
                [c["models"][model]["metrics"][metric]["mean"]["ratio"] for c in cases],
                marker="o",
                label=label,
                color=color,
            )
        ax.axhspan(0.95, 1.05, alpha=0.1, color="green")
        ax.axhline(1, color="gray", linestyle="--")
        ax.set_xticks(positions, labels, rotation=15)
        ax.set_ylabel("Concurrent / solo-active mean")
        ax.set_title(model.upper() + ": E2E vs internal-stage slowdown")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.25)
    fig.tight_layout()
    for suffix in ("png", "svg"):
        fig.savefig(plots / ("green-e2e-internal-stages." + suffix))
    plt.close(fig)


if __name__ == "__main__":
    main()
