"""Render Korean measurement report from completed, audited sustained data only."""

import argparse
import json
from pathlib import Path


def render(root):
    s = json.loads((root / "analysis/summary.json").read_text())
    status = json.loads((root / "verification/controller-status.json").read_text())
    rates = json.loads((root / "rates.json").read_text())
    assert status["state"] == "PASS" and status["restoration"] == "PASS"
    groups = s["groups"]
    text = [
        "# 지속 동시 요청 실험 결과",
        "",
        "## 1. 실험 목적",
        "동일한 지속 유입량에서 MPS 없음 대비 **Qwen 전체응답 E2E p95 증가 0% 이하**, **YOLO E2E p95 20% 이상 감소**를 동시에 만족하는지 확인했다. 기존 10/300 Burst와 별도 시나리오이며 통계는 합치지 않는다.",
        "",
        "## 2. 환경과 부하",
        "- 단일 DGX Spark GB10/48 SM, driver595.99.02, 실제 CUDA runtime13.1. 모델 이미지 Torch build CUDA13.0은 유지하고 host13.1 runtime overlay를 적용했다.",
        "- Qwen3.5-9B BF16/SDPA/고정512 input +128 output tokens, YOLO26l native FP16/동일 bus 이미지/640/batch1. 기존 계측 추론 코드 복사본 사용, Green Context 미사용.",
        "- 각 모델 독립 Pod/Worker/FIFO. Qwen은 동시요청1개, 응답 후 즉시 다음 요청. YOLO는 응답과 무관한 고정 간격 open-loop.",
        f"- YOLO 요청률 **{rates['rates']} req/s**, 120초간 생성, 이후 발행된 전체 요청 drain. 4설정×2요청률×5회=40회. 무작위 complete blocks, 매 trial 새 Pod 및 Q3/Y30 워밍업.",
        f"- 본측정 요청 총 **{s['requests']:,}개**, 독립 raw audit 통과. warmup/pilot은 본측정 통계에 포함하지 않는다.",
        "- E2E는 요청 JSON 직렬화/publish 직전부터 동일 UUID 결과 JSON 파싱 완료까지. 초기 DDS discovery/입력 파일 준비는 제외. 서버와 클라이언트가 동일 CLOCK_MONOTONIC/time namespace인지 확인했다.",
        "- 실제 발행 지연 p95<=10ms, 최대<=100ms를 workload-validity gate로 사전 고정했다. scheduled→응답 지연도 원본에 보존하여 generator 지연 은폐를 방지했다.",
        "",
        "## 3. 예비 실험과 요청률 선정",
        "control(MPS 없음)에서 30초씩 사전 정의한 요청률을 탐색했다. 후반부 평균 서버 Queue 대기<=100ms, 후반 Queue 기울기<=0.1req/s, 오류0인 최대 관측 요청률을 높은 부하로, 그 절반에 가장 가까운 낮은 안정 요청률을 보통 부하로 골랐다. 이는 관측한 격자 내 기준이지 정밀한 최대 처리량 추정은 아니다. 본실험 결과를 보기 전에 rates.json으로 고정했다.",
        "",
        "| 요청률(req/s) | 후반 Queue 평균(ms) | Queue 기울기(req/s) | 오류 |",
        "|---:|---:|---:|---:|",
    ]
    for r in rates["pilot"]:
        text.append(
            f"|{r['rate']:g}|{r['tail_queue_mean_ms']:.3f}|{r['queue_slope_rps']:.4f}|{r['errors']}|"
        )
    text += [
        "",
        "## 4. 주 SLO 결과",
        "**주 판정은 각 실행의 요청 E2E p95를 먼저 계산한 후 5회 평균한 값**이다. 같은 요청률 control과 비교한다. pooled p95는 보조 민감도 분석으로 따로 제시한다. 0% 기준 통과는 관측값 비교이며 모집단의 성능 비열등성/동등성을 증명하지 않는다.",
        "",
        "| YOLO 요청률 | 설정 | Qwen p95(s) | Q 변화 | YOLO p95(ms) | Y 변화 | 두 목표 충족 |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for g in groups:
        d = g["slo"]
        verdict = (
            "기준"
            if g["condition"] == "control"
            else ("관측 통과" if d["both_pass"] else "미충족")
        )
        text.append(
            f"|{g['rate']:g}|{g['condition']}|{g['qwen']['e2e_ms']['p95'] / 1000:.4f}|{d['qwen_change_pct']:+.2f}%|{g['yolo']['e2e_ms']['p95']:.3f}|{d['yolo_change_pct']:+.2f}%|{verdict}|"
        )
    text += [
        "",
        "## 5. 지연 구성 및 Trade-off",
        "",
        "| 요청률 | 설정 | Y Queue 평균(ms) | Y predict 평균(ms) | Y GPU forward 평균(ms) | Q Prefill 평균(ms) | Q TPOT 평균(ms/token) | Q 내부 TTFT 평균(ms) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for g in groups:
        y, q = g["yolo"], g["qwen"]
        text.append(
            f"|{g['rate']:g}|{g['condition']}|{y['queue_ms']['mean']:.3f}|{y['predict_wall_ms']['mean']:.3f}|{y['gpu_forward_span_ms']['mean']:.3f}|{q['gpu_prefill_span_ms']['mean']:.3f}|{q['tpot_ms']['mean']:.3f}|{q['generate_ttft_ms']['mean']:.3f}|"
        )
    text += [
        "",
        "- CUDA Event forward span은 CPU launch/stream 대기 등이 반영될 수 있는 경과시간이며 순수 SM 실행시간이 아니다. 모델 호출 시간 안에 포함되므로 E2E에 다시 더하지 않는다.",
        "- Qwen 내부 TTFT는 생성 내부 첫 토큰 타임스탬프다. ROS가 최종 답변을 한 번 전송하므로 사용자에게 스트리밍된 첫 토큰 지연이 아니다.",
        "- Queue 감소와 model 호출 감소를 구분한다. 안정 부하에서 Queue가 거의 없으면 Burst에서의 큰 Queue 개선 비율이 그대로 나타날 필요가 없다.",
        "",
        "## 6. 처리량·발행 정확도·반복 변동성",
        "",
        "| 요청률 | 설정 | Q 요청수 합 | Q 완료토큰/전체cohort초 평균 | Y 발행률 평균 | Y 120초내 완료률 평균 | 최대 drain(s) | 발행지연 최대(ms) |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for g in groups:
        ts = [
            t
            for t in s["trials"]
            if t["rate"] == g["rate"] and t["condition"] == g["condition"]
        ]
        text.append(
            f"|{g['rate']:g}|{g['condition']}|{sum(t['qwen']['issued'] for t in ts)}|{g['qwen']['output_tokens_per_cohort_s']['mean']:.3f}|{g['yolo']['issue_rate_rps']['mean']:.3f}|{g['yolo']['goodput_by_stop_rps']['mean']:.3f}|{max(t['yolo']['drain_s'] for t in ts):.3f}|{max(t['generator']['lag_max_ms'] for t in ts):.3f}|"
        )
    text += [
        "",
        "### 실행별 p95 범위와 pooled p95 (보조)",
        "",
        "| 요청률 | 설정 | Q 실행 p95 최소~최대(s) | Q pooled p95(s) | Y 실행 p95 최소~최대(ms) | Y pooled p95(ms) | pooled 판정 동일 |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for g in groups:
        q, y = g["qwen"], g["yolo"]
        text.append(
            f"|{g['rate']:g}|{g['condition']}|{q['e2e_ms']['run_p95']['min'] / 1000:.4f}~{q['e2e_ms']['run_p95']['max'] / 1000:.4f}|{q['pooled_e2e_ms']['p95'] / 1000:.4f}|{y['e2e_ms']['run_p95']['min']:.3f}~{y['e2e_ms']['run_p95']['max']:.3f}|{y['pooled_e2e_ms']['p95']:.3f}|{'예' if g['slo']['both_pass'] == g['pooled_slo_sensitivity']['both_pass'] else '아니오'}|"
        )
    text += ["", "## 7. 결론", ""]
    for rate in rates["rates"]:
        passed = [
            g["condition"]
            for g in groups
            if g["rate"] == rate
            and g["condition"] != "control"
            and g["slo"]["both_pass"]
        ]
        text.append(
            f"- **{rate:g} req/s:** 두 관측 SLO를 동시에 충족한 설정: **{', '.join(passed) if passed else '없음'}**."
        )
    text += [
        "",
        "실험 결과에 맞춰 SLO 기준을 사후 완화하지 않는다. 한 설정이 모든 부하/모든 latency 지표에서 최선이라고 주장하지 않는다. 운영 기본 설정은 자동 변경하지 않고, 실험 전 템플릿/replica/MPS 서비스 및 실제 ROS 응답까지 복구했다.",
        "",
        "## 8. 한계",
        "- Qwen은 약10개 수준/run의 작은 표본으로 tail 통계가 불안정할 수 있다. 반복 단위를 요청 수로 부풀리지 않는다. paired round별 변화율은 summary.json에 공개한다.",
        "- Qwen은 closed-loop라 느려질수록 입력 요청 수가 줄어든다. Qwen 과부하/다중클라이언트 Queue 누적은 이번 시나리오의 검증 대상이 아니다.",
        "- 지속 요청은 GPU가 매 순간 100% 사용된다는 의미가 아니다. YOLO도 일정 간격 사이 idle이 생길 수 있다. 이번 본측정에 Nsight를 동시 적용하지 않았으며 과거 별도 병렬성 검증과 구분한다.",
        "- 120초와 두 요청률/네 설정/고정 입력에 한정한 결과다. 장시간 운영·다양한 입력·다른 GPU로 일반화하지 않는다. 클럭 고정/DRAM bandwidth 원인 분리 실험은 하지 않았다.",
        "- 부하 생성 종료 이후 drain 응답도 포함하므로 끝부분은 두 모델이 모두 활성인 구간과 다를 수 있다. 시작/종료/서버 처리 타임스탬프를 전부 보존했다.",
        "- 장애 복구는 별도 실험의 Kubernetes 기본 재시작 검증이다. 본실험에 새로운 복구 최적화를 추가하지 않았다.",
        "",
        "## 9. 산출물",
        "",
        "- [주 통계 JSON](analysis/summary.json), [실행별 CSV](analysis/trials.csv)",
        "- [독립 검증](verification/independent-audit.json), [실행 상태·복원](verification/controller-status.json)",
        "- [부하 선정](rates.json), [무작위 순서](schedule.json), [사전 계획](protocol.ko.md)",
        "- [E2E·SLO](plots/e2e-slo.png), [YOLO Queue](plots/yolo-queue.png), [지연 분해](plots/latency-components.png), [Qwen 단계](plots/qwen-stages.png)",
        "- results/*/final-requests.jsonl: 발행/예정/수신/서버 타임스탬프와 원본 응답. warmup/* 및 pilot/smoke는 별도 보존.",
        "- verification/source-before.sha256 / source-after.sha256: 실행 코드 불변성. raw-files.sha256: 전송 무결성.",
        "",
    ]
    text += [
        "## 10. 결과 해석 및 설정 선택",
        "",
        "- **8 req/s:** 8/40은 Qwen p95를 5.63%, YOLO p95를 16.25% 줄였다. 개선은 있지만 YOLO 목표20%에는 미달한다. 목표를 사후16%로 바꾸지 않는다. 16/32는 YOLO 실행별 p95가 한 반복에서103.09ms까지 증가했고 다른4회는약49.67~50.19ms였다. 이 변동도 삭제하지 않고 포함했다.",
        "- **15 req/s:** 8/40은 Qwen p95 9.66%, YOLO p95 39.61% 감소로 두 관측기준 통과. 16/32도 Qwen3.26%, YOLO43.79% 감소로 통과했다. 16/32의 YOLO 평균 실행-p95가약6ms 낮지만 반복범위가 크게 겹치므로 통계적으로 더 우수한 유일최적점이라고 단정하지 않는다.",
        "- **일반 MPS의 문제:** 15req/s에서 YOLO 평균 Queue가12.95초, p95 Queue가23.39초로 누적되고 마지막 YOLO 응답까지 최대19.39초 추가 drain이 필요했다. 오류0이더라도 지연 SLO와 지속 처리용량을 만족한 것은 아니다. 정적분할에서는 평균 Queue가약0.8~0.9ms였다.",
        "- **8/40의 비용:** 15req/s에서 Qwen Prefill forward207.50→485.62ms, 내부TTFT208.88→486.99ms로 악화됐다. 반면 TPOT100.18→88.86ms/token으로 감소해 전체응답이 빨라졌다. 첫토큰반응성을 주목표로 하면 별도결정이 필요하다.",
        "- **GPU구간을 과장하지 않음:** 15req/s YOLO GPU forward Event 평균은 control11.31ms→8/40 16.84ms로 오히려 증가했다. 이번 E2E개선은 GPU forward단독가속으로 설명할 수 없다. 전체predict26.03→20.69ms, Queue9.26→0.90ms, 전송·클라이언트잔여20.69→13.33ms의 개선을 구분해서 보고한다. 잔여시간을 순수CPU시간이나 단일원인으로 단정하지 않는다.",
        "- **선택:** 두부하에서 Qwen과YOLO의 균형을 고려하면8/40을 운영후보로 유지할 근거가 있다. 하지만 두 요청률 모두에서20%목표를 달성했다는 주장은 불가하다. 15req/s의 YOLO tail만 우선하면16/32도 후보이며, 실제운영설정은 사용자선택 없이 변경하지 않았다.",
        "",
        "## 11. 실험·수집 건전성",
        "",
        "- 초반 v1은 일반MPS/15req/s에서 발행지연p9520.247ms>사전gate10ms로 제외했다. 정상5회도 최종본과 혼합하지 않고 실패원본을 별도보존했다. v2는 YOLO발행을 별도spawn프로세스로 분리해 동일부하·동일gate로40회 모두 재실행했다.",
        "- v2 본측정40회 모두 정상,55,620요청/응답 및55,620개 publication ACK 로그완전일치. 전송원본1,353개SHA검증, 실행소스불변, 보존baseline677개SHA검증 통과.",
        "- 본측정 발행지연 p95의최대값0.691ms, 개별발행지연 최대3.430ms. 부하발행기허용치완화없음.",
        "- [응답발행 ACK 독립검증](verification/publication-audit.json). Kubernetes두Pod Ready1/1,원래템플릿/replica/MPS서비스/실제응답 복구PASS.",
        "",
    ]
    return "\n".join(text)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    a = p.parse_args()
    (a.root / "README.ko.md").write_text(render(a.root))
    print(str(a.root / "README.ko.md"))
