#!/usr/bin/env python3
"""One message per figure: pooled request E2E p95 before/after static8/40."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "results/static-eval/20261110-v1/analysis/summary.json"


def comparison_data(summary):
    conditions = {c["label"]: c for c in summary["conditions"]}
    if not {"control", "static-q8-y40"} <= set(conditions):
        raise ValueError("Both MPS-off baseline and static8/40 are required")
    out = []
    for model in ("qwen", "yolo"):
        metrics = [
            conditions[c]["models"][model]["pooled_descriptive"]["request_e2e_ms"]
            for c in ("control", "static-q8-y40")
        ]
        if metrics[0]["n"] != metrics[1]["n"] or metrics[0]["p95"] <= 0:
            raise ValueError("Comparable complete request cohorts are required")
        before, after = [m["p95"] / 1000 for m in metrics]
        out.append(
            {
                "model": model,
                "metric": "pooled request E2E p95",
                "before_s": before,
                "after_s": after,
                "reduction_pct": (1 - after / before) * 100,
                "requests_per_condition": metrics[0]["n"],
            }
        )
    return out


def plot(rows, output):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "Noto Sans CJK JP",
            "axes.unicode_minus": False,
            "font.size": 13,
            "svg.fonttype": "path",
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.6))
    fig.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.15, wspace=0.32)
    colors = ["#89949F", "#237D8A"]
    for ax, row in zip(axes, rows):
        ax.set_title("Qwen" if row["model"] == "qwen" else "YOLO", fontsize=15, pad=12)
        values = [row["before_s"], row["after_s"]]
        bars = ax.bar([0, 1], values, width=0.54, color=colors, zorder=3)
        maximum = max(values) * 1.23
        ax.set_ylim(0, maximum)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["Baseline", "Ours"], fontsize=13)
        ax.set_ylabel("E2E Latency p95 (s)", fontsize=13)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#E0E5E9", linewidth=0.8)
        ax.tick_params(axis="x", length=0, pad=10)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + maximum * 0.025,
                f"{value:.3f} s",
                ha="center",
                va="bottom",
                fontsize=15,
                fontweight="bold",
            )
    output.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg"):
        fig.savefig(
            str(output / f"burst-request-p95-before-after.{suffix}"),
            dpi=180,
            facecolor="white",
        )
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output-dir", type=Path, default=ROOT / "docs/figures")
    a = p.parse_args()
    rows = comparison_data(json.loads(a.source.read_text()))
    plot(rows, a.output_dir)
    metadata = {
        "source": str(a.source.relative_to(ROOT))
        if ROOT in a.source.parents
        else str(a.source),
        "source_sha256": hashlib.sha256(a.source.read_bytes()).hexdigest(),
        "conditions": ["control", "static-q8-y40"],
        "rows": rows,
        "aggregation": "pooled request p95 across5bursts; NOT a mean, batch makespan, or per-run p95 average",
        "axes": "seconds, both start at0, independent panel maxima",
        "new_measurement": False,
    }
    (a.output_dir / "burst-request-p95-before-after.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n"
    )
    print(str(a.output_dir / "burst-request-p95-before-after.png"))


if __name__ == "__main__":
    main()
