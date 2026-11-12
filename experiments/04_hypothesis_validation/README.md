# 04 · 단계 민감도에서 동시 실행 가설로

[실험 인덱스](../../docs/EXPERIMENT_INDEX.ko.md) · 문서 탐색용이며 소스·원시 자료를 복제하지 않는다.

## Objective

단독 SM 곡선을 서비스 동시 실행에 적용할 수 있는지 분리해서 검증한다.

## Hypothesis

반복 Decode의 추가 SM 이득이 작다면 Qwen 몫을 줄이고 YOLO 몫을 늘려 Burst 지연을 개선할 수 있다. Prefill/TTFT 손해는 별도로 관찰한다.

## Environment

최종 근거는 native driver595.99.02/실제 CUDART13.1, Green 없음. Torch build CUDA13.0과 로드 runtime13.1을 구별한다.

## Workload

동시 Burst Qwen512입력/128고정출력10건, YOLO300건. 초기 closed-loop 및 Green 단독 곡선과 수치를 합치지 않는다.

## Configuration

control, 일반 mps-only, static Qwen/YOLO 8/40·16/32·24/24·32/16·40/8. [설정/무작위 순서 코드](../../diagnostics/mps_static/plan.py).

## Methodology

다섯 비대칭/대칭 분할을 모두 비교한 뒤 후보를 선택한다. 별도 프로파일에서는 partition membership, kernel 및 shared MPS server 실행 구간을 조사한다. 프로파일 시간과 비프로파일 본측정을 합치지 않는다.

## Metrics

요청 E2E p95, 모델별 Burst 완료시간, Qwen 내부 TTFT, 실행 구간 overlap. pooled 요청 p95와 실행5회 완료시간 평균은 서로 다른 집계다.

## Results

다섯 분할 중8/40이 YOLO pooled p95 10.674초로 가장 낮았고 control14.963초 대비28.66% 감소했다. Qwen pooled p95는113.299→111.876초. TTFT 평균188.317→471.930ms는 악화했다.

## Analysis

가설은 이 Burst의 E2E 관측에서 지지되지만 모든 단계가 좋아진 것은 아니다. 8/40은 비교 후 선택된 결과다. 사후 합의한 “Qwen p95 증가 없음, YOLO p95 20% 이상 감소” 기준에 관측상 부합한다. 사전등록 SLO·운영 보장이 아니다.

## Limitations

실행 구간 overlap은 SM/메모리 대역폭 병목의 인과 증명이 아니다. 일반 MPS 지원 비교 자체가 핵심 기여는 아니다. 지속 부하·다른 token 길이·다른 모델에 대한 최적값으로 일반화하지 않는다.

## Artifacts

[7조건 집계 JSON](../../results/static-eval/20261110-v1/analysis/summary.json) · [실행별 CSV](../../results/static-eval/20261110-v1/analysis/trials.csv) · [8/40 portable concurrency export](../../results/static-profile/20261110-final-static-q8-y40/analysis/static-concurrency-summary.json) · [shared-server export](../../results/static-profile/20261110-final-static-q8-y40/analysis/shared-server-residence.json) · [trace hash manifest](../../results/static-profile/20261110-final-static-q8-y40/verification/raw-traces.sha256)
