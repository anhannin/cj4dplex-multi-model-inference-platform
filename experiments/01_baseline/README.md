# 01 · 최적화 전 다섯 조건 기준선

[실험 인덱스](../../docs/EXPERIMENT_INDEX.ko.md) · 문서 탐색용이며 소스·원시 자료를 복제하지 않는다.

## Objective

단독 실행, 동시 상주, 동시 활성의 차이를 분리해 다음 진단의 출발점을 만든다.

## Hypothesis

단순 모델 상주보다 실제 동시 추론에서 지연이 커지는가?

## Environment

DGX Spark GB10 48 SM, 초기 driver580/CUDART13.0 환경. 최종 native595/CUDART13.1 Burst와 다른 실험이다.

## Workload

Qwen3.5-9B BF16, 짧은 고정 프롬프트 5개(23~27입력 토큰), 최대128 출력. YOLO26l FP16, 이미지2개,640/batch1. 모델별 closed-loop C1.

## Configuration

①Qwen Pod만 ②YOLO Pod만 ③둘 상주/Qwen 활성 ④둘 상주/YOLO 활성 ⑤둘 동시 활성. 모델별 FIFO8/Worker1. MPS·Green·SM 분할 없음.

## Methodology

각 활성 모델 warmup5 제외. ①③Qwen 각30건, ②④YOLO 각300건, ⑤Qwen30건 종료까지 YOLO11,634건. 단일 순서 실행. [실행 코드](../../benchmark/run_five_phases.sh)와 [집계 코드](../../benchmark/report_five_phases.py)를 대조한다.

## Metrics

클라이언트 E2E, 서버 generate/TTFT/TPOT, YOLO predict/inference, 큐 대기, 요청 처리량. TTFT≠Prefill, generate≠순수 GPU 시간, 잔여구간≠순수 네트워크.

## Results

본측정12,324건 성공. 같은 Pod의 개별 활성 대비 동시 활성에서 Qwen 평균 E2E +37.62%, YOLO 평균 E2E +71.24%. YOLO inference +117.73%. [표/원본 해설](../../results/latency-baseline/README.ko.md).

## Analysis

상주 자체보다는 동시 진행 간섭을 우선 조사할 근거다. C1 큐 대기는 작아 대규모 대기열 문제를 재현한 결과는 아니다. 다음 단계는 GPU 경로 진단이다.

## Limitations

순서 교차·반복 없음, Qwen N30, 주파수 고정 없음. p95의 단조 악화도 보장하지 않는다. 재시작 사이 문자열 차이가 있어 입력/출력 토큰 수 일치와 문자열 재현성을 구별한다. 최종 Burst 개선율의 직접 분모로 쓰지 않는다.

## Artifacts

[원시 phase별 자료](../../results/latency-baseline/phases/) · [CSV](../../results/latency-baseline/comparison.csv) · [JSON](../../results/latency-baseline/comparison.json) · [검증](../../results/latency-baseline/validation.json) · [동결 manifest](../../baseline/MANIFEST.json) · [프로토콜](../../docs/experiments/2026-11-03-latency-baseline.md)
