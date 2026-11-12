#!/usr/bin/env python3
"""Generate submission tables exclusively from preserved experiment summaries."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def evidence():
    paths = {
        "burst": "results/static-eval/20261110-v1/analysis/summary.json",
        "fault": "results/fault-idle/20261110-v1/analysis/summary.json",
    }
    raw = {k: json.loads((ROOT / v).read_text()) for k, v in paths.items()}
    return paths, raw


def render():
    paths, raw = evidence()
    facts = {
        "provenance": {
            k: {
                "path": v,
                "sha256": hashlib.sha256((ROOT / v).read_bytes()).hexdigest(),
            }
            for k, v in paths.items()
        },
        "burst": [],
        "fault": raw["fault"]["recovery"],
    }
    lines = [
        "# 주요 결과표 — 원본 JSON에서 생성",
        "",
        "단위와 집계방법을 시나리오별로 구분한다. 생성: `python3 scripts/render_submission_tables.py`.",
        "",
        "## Burst: Qwen10 / YOLO300 동시 발행",
        "완료시간=실행5회의 평균. 요청 p95=각 조건 전체 요청을 합친 기술통계(pooled). Qwen50/YOLO1500개를 독립적인 실험 반복1500회로 취급하지 않는다.",
        "",
        "| 설정 | Qwen10개 완료(s) | YOLO300개 완료(s) | Qwen 요청 E2E p95(s) | YOLO 요청 E2E p95(s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for c in raw["burst"]["conditions"]:
        row = {
            "condition": c["label"],
            "qwen_completion_s": c["qwen_ms"]["mean"] / 1000,
            "yolo_completion_s": c["yolo_ms"]["mean"] / 1000,
            "qwen_p95_s": c["models"]["qwen"]["pooled_descriptive"]["request_e2e_ms"][
                "p95"
            ]
            / 1000,
            "yolo_p95_s": c["models"]["yolo"]["pooled_descriptive"]["request_e2e_ms"][
                "p95"
            ]
            / 1000,
        }
        facts["burst"].append(row)
        lines.append(
            "|{condition}|{qwen_completion_s:.3f}|{yolo_completion_s:.3f}|{qwen_p95_s:.3f}|{yolo_p95_s:.3f}|".format(
                **row
            )
        )
    lines += [
        "",
        "## 유휴 프로세스 장애 — Kubernetes 기본 재시작",
        "SIGKILL 직전부터의 초 단위 경과. 탐지·container시작·Ready는250ms polling 관측 상한값, 첫 정상응답은클라이언트수신시각.",
        "",
        "| 반복 | 탐지 관측(s) | Container 시작 관측(s) | 첫 정상 응답(s) | Ready 관측(s) |",
        "|---|---:|---:|---:|---:|",
    ]
    for i, t in enumerate(raw["fault"]["trials"]):
        lines.append(
            f"|{i + 1}|{t['detect_observed_ms'] / 1000:.3f}|{t['container_start_observed_ms'] / 1000:.3f}|{t['first_valid_response_ms'] / 1000:.3f}|{t['ready_observed_ms'] / 1000:.3f}|"
        )
    lines += ["", "원본 출처:"] + [
        f"- `{p}` (SHA-256 `{facts['provenance'][k]['sha256']}`)"
        for k, p in paths.items()
    ]
    return "\n".join(lines) + "\n", facts


def render_burst():
    """Performance-report scope: only the seven fixed-work Burst conditions."""
    _, facts = render()
    order = [
        "control",
        "mps-only",
        "static-q8-y40",
        "static-q16-y32",
        "static-q24-y24",
        "static-q32-y16",
        "static-q40-y8",
    ]
    lines = [
        "### Burst 전체 비교",
        "",
        "완료시간은 실행5회의 평균이다. 요청 E2E p95는 조건별 전체 요청을 합친 기술통계(pooled)다. 조건당Qwen50개·YOLO1500개이며 독립 실행 반복은5회다.",
        "",
        "| 설정(Qwen/YOLO SM) | Qwen10개 완료(s) | YOLO300개 완료(s) | Qwen 요청 E2E p95(s) | YOLO 요청 E2E p95(s) |",
        "|---|---:|---:|---:|---:|",
    ]
    by_name = {r["condition"]: r for r in facts["burst"]}
    for name in order:
        r = by_name[name]
        lines.append(
            "|{condition}|{qwen_completion_s:.3f}|{yolo_completion_s:.3f}|{qwen_p95_s:.3f}|{yolo_p95_s:.3f}|".format(
                **r
            )
        )
    _, raw = evidence()
    conditions = {c["label"]: c for c in raw["burst"]["conditions"]}
    control, candidate = conditions["control"], conditions["static-q8-y40"]

    def metric(c, model, key, field="mean"):
        return c["models"][model]["pooled_descriptive"][key][field]

    summary = [
        (
            "YOLO 300건 완료 평균(s)",
            control["yolo_ms"]["mean"] / 1000,
            candidate["yolo_ms"]["mean"] / 1000,
        ),
        (
            "YOLO 요청 E2E 평균(s)",
            metric(control, "yolo", "request_e2e_ms") / 1000,
            metric(candidate, "yolo", "request_e2e_ms") / 1000,
        ),
        (
            "YOLO 요청 E2E p95(s)",
            metric(control, "yolo", "request_e2e_ms", "p95") / 1000,
            metric(candidate, "yolo", "request_e2e_ms", "p95") / 1000,
        ),
        (
            "Qwen 요청 E2E p95(s)",
            metric(control, "qwen", "request_e2e_ms", "p95") / 1000,
            metric(candidate, "qwen", "request_e2e_ms", "p95") / 1000,
        ),
        (
            "Qwen 내부 TTFT 평균(ms)",
            metric(control, "qwen", "generate_ttft_ms"),
            metric(candidate, "qwen", "generate_ttft_ms"),
        ),
        (
            "전체 310건 완료 평균(s)",
            control["total_ms"]["mean"] / 1000,
            candidate["total_ms"]["mean"] / 1000,
        ),
    ]
    lines += [
        "",
        "### 핵심 지표 요약 — MPS 없음 대비 정적 8/40",
        "",
        "| 성능 지표 | MPS 없음 | 정적 8/40 | 변화율 |",
        "|---|---:|---:|---:|",
    ]
    for label, before, after in summary:
        lines.append(
            f"| {label} | {before:.3f} | {after:.3f} | {(after / before - 1) * 100:+.2f}% |"
        )
    lines += [
        "",
        "출처: `results/static-eval/20261110-v1/analysis/summary.json`. 생성: `python3 scripts/render_submission_tables.py`.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text, facts = render()
    out = ROOT / "docs/submission"
    out.mkdir(exist_ok=True)
    (out / "RESULT_TABLES.ko.md").write_text(text)
    (out / "metrics.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=2) + "\n"
    )

    (out / "BURST_TABLES.ko.md").write_text(render_burst())
