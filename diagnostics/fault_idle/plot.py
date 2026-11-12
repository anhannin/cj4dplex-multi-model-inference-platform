"""Fault/recovery observed times, not GPU occupancy or steady-load SLO proof."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

p = argparse.ArgumentParser()
p.add_argument("--root", required=True, type=Path)
a = p.parse_args()
root = a.root
s = json.loads((root / "analysis/summary.json").read_text())
out = root / "plots"
out.mkdir(exist_ok=True)
plt.rcParams.update(
    {"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False, "savefig.dpi": 170}
)
fig, ax = plt.subplots(figsize=(12, 4.5))
for i, r in enumerate(s["trials"]):
    start = r["container_start_observed_ms"] / 1000
    functional = r["first_valid_response_ms"] / 1000
    ready = r["ready_observed_ms"] / 1000
    ax.broken_barh([(0, start)], (i - 0.25, 0.5), facecolors="#d95f59")
    ax.broken_barh([(start, functional - start)], (i - 0.25, 0.5), facecolors="#f0b66e")
    ax.broken_barh(
        [(functional, max(0, ready - functional))],
        (i - 0.25, 0.5),
        facecolors="#75b878",
    )
    ax.scatter(
        [r["detect_observed_ms"] / 1000],
        [i],
        color="#7b3294",
        marker="v",
        s=55,
        zorder=4,
    )
    ax.scatter([ready], [i], color="#222222", marker="D", s=38, zorder=4)
    ax.text(
        functional,
        i - 0.31,
        f"첫 정상 결과 {functional:.3f}s",
        ha="center",
        va="bottom",
        fontsize=10,
    )
    ax.text(ready + 0.08, i, f"Ready 관측 {ready:.3f}s", va="center", fontsize=9)
ax.set_yticks(range(3))
ax.set_yticklabels(["독립 시험1", "독립 시험2", "독립 시험3"])
ax.set_xlim(0, 10.2)
ax.set_ylim(2.6, -0.8)
ax.set_xlabel("GPU 유휴 YOLO Node SIGKILL 시점 이후 [초]")
ax.grid(axis="x", alpha=0.25)
fig.suptitle(
    "프로세스 장애 후 자동 컨테이너 재시작과 실제 응답 복구\n시작/Ready/탐지는 외부 API 관측 시각 — GPU 커널 타임라인 아님",
    fontsize=12,
)
fig.legend(
    handles=[
        Patch(facecolor="#d95f59", label="새 컨테이너 시작 관측 전"),
        Patch(facecolor="#f0b66e", label="시작 관측 → 첫 정상 응답"),
        Patch(facecolor="#75b878", label="응답 가능, Ready 아직 미관측"),
    ],
    loc="lower center",
    ncol=3,
    fontsize=9,
    frameon=False,
)
fig.tight_layout(rect=(0, 0.1, 1, 0.89))
fig.savefig(out / "recovery-timeline.png")
fig.savefig(out / "recovery-timeline.svg")
plt.close(fig)
coh = s["qwen"]["cohorts"]
keys = [
    "before_first_fault",
    "overlap_fault_recovery",
    "after_last_functional_recovery",
]
labels = ["첫 장애 전 (N=3)", "장애·복구와 겹친 요청 (N=3)", "마지막 복구 후 (N=2)"]
fig, ax = plt.subplots(figsize=(10, 4.5))
means = [coh[k]["mean"] / 1000 for k in keys]
ax.bar(range(3), means, color=["#699bd0", "#f0b66e", "#75b878"], width=0.55)
for i, k in enumerate(keys):
    ax.text(i, means[i] + 0.1, f"{means[i]:.3f}s", ha="center")
ax.set_xticks(range(3))
ax.set_xticklabels(labels, fontsize=9)
ax.set_ylim(0, 13)
ax.set_ylabel("Qwen 요청 E2E 평균 [초]")
ax.grid(axis="y", alpha=0.25)
fig.suptitle(
    "Qwen 응답 오류0 / 프로세스·MPS 서버 PID 유지\n서로 다른 작은 관측 집단이며, 정상 성능 SLO 0% 악화 검증은 아님",
    fontsize=12,
)
fig.tight_layout(rect=(0, 0, 1, 0.88))
fig.savefig(out / "qwen-observed-impact.png")
plt.close(fig)
print(out)
