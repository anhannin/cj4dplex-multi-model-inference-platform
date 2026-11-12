"""Plot summary.json with system matplotlib, never mix Burst and sustained cohorts."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("--root", type=Path, required=True)
a = p.parse_args()
s = json.loads((a.root / "analysis/summary.json").read_text())
out = a.root / "plots"
out.mkdir(exist_ok=True)
plt.rcParams["font.family"] = "Noto Sans CJK JP"
plt.rcParams["axes.unicode_minus"] = False
rates = sorted({g["rate"] for g in s["groups"]})
names = ["control", "mps-only", "static-q8-y40", "static-q16-y32"]
labels = ["MPS 없음", "일반 MPS", "정적 8/40", "정적 16/32"]
colors = ["#607D8B", "#E69F00", "#0072B2", "#009E73"]


def save(fig, name):
    fig.tight_layout(
        rect=[0, 0, 1, 0.94] if fig._suptitle is not None else [0, 0, 1, 1]
    )
    fig.savefig(str(out / (name + ".png")), dpi=180)
    fig.savefig(str(out / (name + ".svg")))
    plt.close(fig)


def group(rate, name):
    return next(g for g in s["groups"] if g["rate"] == rate and g["condition"] == name)


fig, axes = plt.subplots(len(rates), 2, figsize=(12, 4 * len(rates)), squeeze=False)
for i, rate in enumerate(rates):
    for j, m in enumerate(["qwen", "yolo"]):
        ax = axes[i, j]
        gs = [group(rate, name) for name in names]
        means = [g[m]["e2e_ms"]["p95"] / 1000 for g in gs]
        low = [v - g[m]["e2e_ms"]["run_p95"]["min"] / 1000 for v, g in zip(means, gs)]
        high = [g[m]["e2e_ms"]["run_p95"]["max"] / 1000 - v for v, g in zip(means, gs)]
        ax.bar(range(4), means, color=colors, yerr=[low, high], capsize=4)
        target = means[0] * (1 if m == "qwen" else 0.8)
        ax.axhline(target, linestyle="--", color="#D55E00", label="SLO 기준")
        for k, v in enumerate(means):
            ax.text(k, v, "%.3f" % v, ha="center", va="bottom", fontsize=9)
        ax.set_xticks(range(4))
        ax.set_xticklabels(labels)
        ax.set_ylabel("요청 E2E p95 (s)")
        if m == "yolo" and max(means) / min(means) > 20:
            ax.set_yscale("log")
            ax.set_ylabel("요청 E2E p95 (s, 로그 축)")
        ax.set_title("%s / YOLO %g req/s" % (m, rate))
        ax.legend()
        ax.grid(axis="y", alpha=0.2)
fig.suptitle(
    "지속 부하: 실행별 p95의 5회 평균 / 오차막대=실행별 최소~최대", fontsize=12
)
fig.tight_layout(rect=[0, 0, 1, 0.96])
save(fig, "e2e-slo")

fig, axes = plt.subplots(len(rates), 1, figsize=(12, 3.7 * len(rates)), squeeze=False)
for i, rate in enumerate(rates):
    ax = axes[i, 0]
    for name, label, color in zip(names, labels, colors):
        ts = [t for t in s["trials"] if t["rate"] == rate and t["condition"] == name]
        depth = np.array([[point[1] for point in t["queue_series"]] for t in ts])
        x = [point[0] for point in ts[0]["queue_series"]]
        ax.plot(x, depth.mean(axis=0), label=label, color=color)
        ax.fill_between(
            x, depth.min(axis=0), depth.max(axis=0), color=color, alpha=0.13
        )
    ax.set_title("YOLO %g req/s: 서버 FIFO 대기 요청 수 (평균, 음영=반복 범위)" % rate)
    ax.set_ylabel("Queue 길이")
    ax.set_xlabel("부하 시작 후 시간 (s)")
    ax.legend()
    ax.grid(alpha=0.2)
save(fig, "yolo-queue")

fig, axes = plt.subplots(len(rates), 2, figsize=(13, 4 * len(rates)), squeeze=False)
for i, rate in enumerate(rates):
    for j, m in enumerate(["qwen", "yolo"]):
        ax = axes[i, j]
        gs = [group(rate, n) for n in names]
        bottom = np.zeros(4)
        pipe = "generate_wall_ms" if m == "qwen" else "predict_wall_ms"
        for key, label, color in [
            ("queue_ms", "서버 Queue", "#E69F00"),
            (pipe, "모델 호출", "#0072B2"),
            ("server_nonpipeline_ms", "서버 기타", "#009E73"),
            ("transport_client_residual_ms", "전송·클라이언트 잔여", "#CC79A7"),
        ]:
            vals = np.array([g[m][key]["mean"] / 1000 for g in gs])
            ax.bar(range(4), vals, bottom=bottom, label=label, color=color)
            bottom += vals
        ax.set_xticks(range(4))
        ax.set_xticklabels(labels)
        ax.set_ylabel("요청 평균 지연 (s)")
        ax.set_title("%s / YOLO %g req/s" % (m, rate))
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.2)
fig.suptitle("비중복 E2E 분해: CUDA Event 구간은 모델 호출 안에 포함되므로 더하지 않음")
save(fig, "latency-components")

fig, axes = plt.subplots(len(rates), 3, figsize=(15, 3.7 * len(rates)), squeeze=False)
for i, rate in enumerate(rates):
    gs = [group(rate, n) for n in names]
    for j, key, title in [
        (0, "gpu_prefill_span_ms", "Qwen Prefill forward (ms)"),
        (1, "tpot_ms", "Qwen TPOT (ms/token)"),
        (2, "generate_ttft_ms", "Qwen 내부 TTFT (ms)"),
    ]:
        ax = axes[i, j]
        ax.bar(range(4), [g["qwen"][key]["mean"] for g in gs], color=colors)
        ax.set_xticks(range(4))
        ax.set_xticklabels(labels, rotation=10)
        ax.set_title("%s / YOLO %g req/s" % (title, rate))
        ax.grid(axis="y", alpha=0.2)
save(fig, "qwen-stages")
print(str(out))
