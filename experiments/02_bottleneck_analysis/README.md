# 02 · 병목 후보를 좁히는 실행 경로 진단

[실험 인덱스](../../docs/EXPERIMENT_INDEX.ko.md) · 문서 탐색용이며 소스·원시 자료를 복제하지 않는다.

## Objective

기준선 악화가 모델 작업량·애플리케이션 큐·GPU 실행 경로 중 어디와 동반되는지 확인한다.

## Hypothesis

동일 작업량에서 GPU 실행과 명령 대기 구간이 늘어난다면 GPU 자원 배분 실험을 검토할 근거가 된다.

## Environment

초기580/CUDART13.0 계열 기준선 환경. Nsight Systems2025.5.1로 수집·export/stats 버전을 맞췄다.

## Workload

두 모델 모두 상주. Qwen만 활성2건, YOLO만 활성100건, 동시 Qwen2/YOLO780건. 같은128 출력 토큰과 이미지 순서.

## Configuration

최적화 없음. 원본 Node 대신 NVTX/capture gate가 있는 진단 사본. CPU sampling/context switch 및 SM/DRAM hardware counter는 수집하지 않았다.

## Methodology

워밍업 후 짧은 cudaProfilerApi 수집. 요청 NVTX와 CUDA API/kernel correlation 검증. [진단 실행 묶음](../../results/nsight-diagnostics/scripts/)의 export/분석 경로를 따른다.

## Metrics

kernel 구간 합집합, launch API 반환→kernel 시작 시각차, 동기화 API 구간, NVTX wall. 겹치는 kernel 대기 구간을 요청 시간으로 단순 합산하지 않는다.

## Results

Qwen generate NVTX 11.704→16.136초, GPU kernel 구간 합집합11.012→14.912초. YOLO predict10.370→30.097ms, kernel별 시작 시각차 평균0.622→5.492ms. [진단 보고서](../../results/nsight-diagnostics/README.ko.md).

## Analysis

고정 작업량에서 GPU 실행/대기 악화와 동반됨을 관측했다. SM 민감도와 모델 단계 차이를 다음 실험으로 검증한다. 일반 MPS 지원 여부는 보조 환경 검증이지 핵심 결론이 아니다.

## Limitations

프로파일러가 붙은 짧은 진단이며 기준선 성능 표를 대체하지 않는다. kernel elapsed는 occupancy/active cycles가 아니고 SM 포화·대역폭 포화·context switching 원인을 분리하지 못한다. memcpy API 체류시간도 순수 복사시간이 아니다.

## Artifacts

[분석 JSON](../../results/nsight-diagnostics/analysis.json) · [비교 CSV](../../results/nsight-diagnostics/comparison.csv) · [portable Qwen kernel CSV](../../results/nsight-diagnostics/qwen-concurrent-kernels.csv) · [portable YOLO kernel CSV](../../results/nsight-diagnostics/yolo-concurrent-kernels.csv) · [correlation 검증](../../results/nsight-diagnostics/correlation-validation.json) · [export 로그](../../results/nsight-diagnostics/evidence/)
