# 05 · native static MPS Burst 비교와 선택

[실험 인덱스](../../docs/EXPERIMENT_INDEX.ko.md) · 문서 탐색용이며 소스·원시 자료를 복제하지 않는다.

## Objective

동일 최종 환경에서 정적 분할의 서비스 성능을 비교해 선택 근거와 비용을 남긴다.

## Hypothesis

48 SM을 모델별 민감도에 맞춰 비대칭 배분하면 Qwen 전체 완료를 유지하면서 YOLO tail을 줄일 수 있다.

## Environment

GB10/native595.99.02/CUDART13.1. frozen 모델 이미지를 유지하고 호스트 CUDA13.1을 read-only overlay. Green 없음.

## Workload

실행마다 Qwen10건(512입력/128고정출력)+YOLO300건=310건 Burst. 초기580 다섯 조건 기준선과 다른 workload이다.

## Configuration

control/mps-only/static 다섯 분할=7조건. native opaque partition ID와 실제 allocation/membership을 확인하며 percentage provisioning으로 대체하지 않는다. [구성](../../diagnostics/mps_static/config.py).

## Methodology

고정 seed20261110의 complete-block 무작위 순서, 조건별5회=35실행. timed10,850응답+warmup1,155응답=감사12,005응답. [eval runner](../../diagnostics/mps_static/eval_runner.py)와 [보존 src 묶음](../../results/static-eval/20261110-v1/src/) 참조.

## Metrics

완료시간은 실행5회 평균. 요청 E2E p95는 조건별 Qwen50/YOLO1500요청 pooled 기술통계이며 독립 반복 수는5다. [생성 표](../../docs/submission/BURST_TABLES.ko.md).

## Results

control→8/40: YOLO300건 완료 평균16.322→11.592초(-28.98%), E2E 평균7.759→5.610초(-27.70%), pooled p95 14.963→10.674초(-28.66%). Qwen pooled p95 113.299→111.876초(-1.26%), 전체310건 완료 평균113.361→111.887초(-1.30%).

## Analysis

8/40은 이 조건에서 유리한 관측 선택이다. mps-only의 YOLO p95 23.404초는 단순 MPS 활성화가 개선을 보장하지 않음을 보여준다. Qwen TTFT +150.60% 비용과 E2E 기준을 함께 보고한다.

## Limitations

사후 SLO 기준에 관측상 부합할 뿐 통계적 보장/상시 운영 약속은 아니다. CPU 재집계는 GPU 재실험이 아니다. eval runner의 base_runner/control_runner 등 alias와 복사 src 의존성, hostPath·모델·ROS/K8s·MPS 준비가 필요하므로 단일 명령 이식형 재현을 주장하지 않는다. [재현 경계](../../docs/REPRODUCIBILITY.ko.md).

## Artifacts

[원시 실행](../../results/static-eval/20261110-v1/results/) · [워밍업](../../results/static-eval/20261110-v1/warmup/) · [JSON](../../results/static-eval/20261110-v1/analysis/summary.json) · [CSV](../../results/static-eval/20261110-v1/analysis/trials.csv) · [검증](../../results/static-eval/20261110-v1/verification/) · [그림](../../docs/figures/burst-request-p95-before-after.svg) · [그림 데이터](../../docs/figures/burst-request-p95-before-after.json)
