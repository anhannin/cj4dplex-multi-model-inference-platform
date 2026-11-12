# 03 · 단일 활성 모델의 SM 민감도

[실험 인덱스](../../docs/EXPERIMENT_INDEX.ko.md) · 문서 탐색용이며 소스·원시 자료를 복제하지 않는다.

## Objective

모델과 단계마다 SM 증가의 이득이 같은지 확인해 비대칭 배분 가설을 만든다.

## Hypothesis

Qwen Prefill은 SM에 민감하지만 반복 Decode는 추가 SM 이득이 제한적일 수 있다. YOLO는 별도의 곡선을 가진다.

## Environment

GB10 48 SM, driver580.173.02/CUDA13.0, Green Context. 한 번에 한 모델만 활성. 최종595 static MPS의 pooled 동시 실행 실험이 아니다.

## Workload

Qwen 정확히512 입력/128 고정 출력, batch1/greedy. 첫 forward512와 one-token Decode127회. YOLO 고정 bus.jpg/FP16/640×640/batch1.

## Configuration

Green 실제 SM8/16/24/32/40/48와 일반 primary full48 reference를 분리. 각 point/round warmup Qwen3/YOLO10 제외.

## Methodology

두 라운드 순서 [24,40,48,32,8,16]와 역순. SM당 Qwen30/YOLO100 측정. 8/48 양 끝은 별도 CUPTI trace로 Green kernel 경로 검증. [runner](../../diagnostics/sm_sweep/run_model.py) 및 [어댑터](../../diagnostics/sm_sweep/green_sweep.cu).

## Metrics

forward 앞뒤 CUDA-event elapsed, generate/predict wall, TTFT/TPOT, shape/token/fidelity. event 시간에도 dispatch 공백·대기가 포함될 수 있어 순수 kernel busy time이라 부르지 않는다. Decode127개 평균은 생성 한 건의 표본이다.

## Results

8→48 SM: YOLO forward20.44→7.67ms, Qwen Prefill539.50→186.13ms, Decode96.99→91.53ms/token. Qwen generate wall12.906→11.847초. [결과 해설](../../results/sm-sweep/README.ko.md).

## Analysis

Prefill과 반복 Decode의 민감도가 달랐다. 전체 생성이 비슷해도 TTFT 손해는 숨겨질 수 있다. Qwen16/YOLO32 등은 후속 후보일 뿐이며 8/40을 사전에 정한 결론이 아니다.

## Limitations

단일 입력/모델·eager 조건, 단독 활성 곡선이다. 동시 E2E 개선·물리 SM 전역 예약·대역폭 병목의 인과 증명이 아니다. SD 오차막대는 신뢰구간이 아니다. 실패 v1을 성공 v2에 합산하지 않는다.

## Artifacts

[원시 v2](../../results/sm-sweep/20261109-v2/) · [CSV](../../results/sm-sweep/20261109-v2/plots/sm-latency-summary.csv) · [JSON](../../results/sm-sweep/20261109-v2/plots/analysis.json) · [그림 SVG](../../results/sm-sweep/20261109-v2/plots/sm-latency-model-stages.svg) · [감사](../../results/sm-sweep/20261109-v2/verification/main-audit.json) · [portable kernel coverage](../../results/sm-sweep/20261109-v2/verification/pilot-qwen-coverage.json) · [보존 checksum](../../results/sm-sweep/20261109-v2/ARTIFACTS_SHA256SUMS)
