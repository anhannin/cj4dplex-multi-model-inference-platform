# 실험 인덱스 · 문제 발견에서 선택까지

이 문서는 원본 코드·원시 자료의 위치를 연결하는 탐색 계층이다. 자료를 새 실험 디렉터리로 복사하거나 기존 실행 결과를 덮어쓰지 않는다. 주 성능 결론은 **최종 native static MPS Burst 비교**에 한정한다.

## 의사결정 흐름

| 순서 | 질문과 다음 결정 | 실험 문서 | 원본 코드 / 근거 |
|---|---|---|---|
| 01 | 상주인가 동시 실행인가? → 동시 활성 간섭 진단 | [기준선](../experiments/01_baseline/README.md) | [benchmark](../benchmark/) / [5조건 CSV](../results/latency-baseline/comparison.csv) |
| 02 | 어떤 실행 구간이 악화되는가? → SM 민감도 검증 | [병목 후보 분석](../experiments/02_bottleneck_analysis/README.md) | [진단 scripts](../results/nsight-diagnostics/scripts/) / [portable kernel CSV](../results/nsight-diagnostics/yolo-concurrent-kernels.csv) |
| 03 | 모델·Prefill·Decode의 SM 곡선이 같은가? → 비대칭 배분 가설 | [SM 민감도](../experiments/03_sm_sensitivity/README.md) | [Green sweep](../diagnostics/sm_sweep/) / [단계별 CSV](../results/sm-sweep/20261109-v2/plots/sm-latency-summary.csv) |
| 04 | 단독 곡선의 가설이 동시 Burst에서도 지지되는가? | [가설 검증](../experiments/04_hypothesis_validation/README.md) | [partition 계획](../diagnostics/mps_static/plan.py) / [portable overlap export](../results/static-profile/20261110-final-static-q8-y40/analysis/static-concurrency-summary.json) |
| 05 | 다섯 분할 중 어떤 것이 유리한가? → 비교 후8/40 선택 | [static MPS 최적화](../experiments/05_static_mps_optimization/README.md) | [eval runner](../diagnostics/mps_static/eval_runner.py) / [7조건×5회 JSON](../results/static-eval/20261110-v1/analysis/summary.json) |
| 06 | 실제 요청 health와 제한된 재시작은 어떻게 확인했는가? | [장애/복구](../experiments/06_fault_recovery/README.md) | [fault controller](../diagnostics/fault_idle/controller.py) / [3회 관측 CSV](../results/fault-idle/20261110-v1/analysis/trials.csv) |

## 환경과 지표를 합치지 않는 규칙

- 초기 기준선은 driver580/CUDART13.0, 짧은 프롬프트·모델별 closed-loop C1의 다섯 조건이다. 최종 결과는 native595.99.02/실제 CUDART13.1, Green 없는 동시 Burst다. Torch build CUDA13.0은 실제 로드 runtime 버전과 다르다.
- Green SM sweep은 초기580에서 **한 번에 한 모델**을 실행했다. pooled static MPS 동시 실행 수치가 아니다. Qwen Prefill은 SM에 민감하고 반복 Decode의 추가 SM 이득은 작았다는 관측이 후속 가설의 출발점이다. 대역폭 병목의 인과 증명은 아니다.
- 최종 Burst는 Qwen512입력/128고정출력10건+YOLO300건,7조건×5회. 본측정10,850응답과 warmup1,155응답을 합친 감사 분모가12,005다. 완료시간은 실행5회 평균, 요청 p95는 조건별 요청 pooled 통계이며 이를 같은 통계로 부르지 않는다.
- 8/40은 다섯 분할 비교 후 선택했다. 사후 합의한 “Qwen p95 증가 없음, YOLO p95 20% 이상 감소”에 관측상 부합할 뿐 사전등록 SLO·통계 보장·운영 SLA는 아니다. Qwen TTFT 손해를 숨기지 않는다.
- 일반 MPS 지원 비교는 보조 맥락이다. CUDA-event elapsed나 trace overlap을 순수 GPU busy time·메모리 대역폭 포화의 증명으로 해석하지 않는다.
- 유휴 SIGKILL은 YOLO Node 전체 프로세스3회, 첫 응답 평균4.390초(4.163~4.504초)다. IPC/Ready/shm/linger 운영 사례와 분리하며 IPC의 정확한 MTTR, in-flight 복구·큐 영속성·HA를 주장하지 않는다.

## 자료 보존과 재현 경계

[재현 안내](REPRODUCIBILITY.ko.md)와 [실행 명령 설명](REPRO_COMMANDS.ko.md)을 먼저 읽는다. `diagnostics/`는 원본 코드, 각 `results/<실험>/<run>/src/`는 당시 helper alias·복사 의존성을 포함한 실행 묶음이다. 예를 들어 eval runner는 `base_runner`/`control_runner`를 import하며 호스트 `GREEN_BURST_ROOT`, 모델 이미지·가중치, ROS/K8s/MPS 및 hostPath가 필요하다. Git만으로 한 명령 GPU 완전 재현을 보장하지 않는다. CPU 재집계는 임시 복사본에서 수행해 원시 자료를 보존한다.

대용량 `.nsys-rep`·SQLite는 **의도적으로 로컬 전용 제외**된 자료다. 기존 보고서의 당시 경로 언급이 제출 트리에 해당 바이너리가 있다는 뜻은 아니다. 현재 존재하는 [portable kernel CSV](../results/nsight-diagnostics/qwen-concurrent-kernels.csv), [coverage JSON](../results/sm-sweep/20261109-v2/verification/pilot-qwen-coverage.json), [concurrency JSON](../results/static-profile/20261110-final-static-q8-y40/analysis/static-concurrency-summary.json), [trace hash manifest](../results/static-profile/20261110-final-static-q8-y40/verification/raw-traces.sha256), [sweep artifact checksum](../results/sm-sweep/20261109-v2/ARTIFACTS_SHA256SUMS)을 연결한다. checksum의 과거 바이너리 항목은 보존 이력이지 현재 payload 존재 증명이 아니다. 없는 trace 링크를 새로 만들지 않는다.

## 본문 밖에 보존한 선택적 연구 자료

아래는 실제로 수행된 과거/별도 연구의 탐색용 색인이다. 수행하지 않았다는 뜻이 아니며 주 Burst 개선율의 분모·표본에 합치지 않는다. 실패·수정 전 실행도 그대로 보존한다.

| 범위 | 코드 | 보존 자료 |
|---|---|---|
| Green 지원·실제 모델 경로/IPC | [green_context](../diagnostics/green_context/) | [green-context](../results/green-context/) |
| Green E2E/Burst 탐색 | [green_e2e](../diagnostics/green_e2e/), [green_burst](../diagnostics/green_burst/) | [green-e2e](../results/green-e2e/), [green-burst](../results/green-burst/) |
| 일반 MPS 동시성/Burst·과거 static 지원 진단 | [mps_concurrency](../diagnostics/mps_concurrency/), [mps_burst](../diagnostics/mps_burst/) | [mps-concurrency](../results/mps-concurrency/), [mps-static](../results/mps-static/) |
| kernel overlap 보조 진단 | [kernel_overlap](../diagnostics/kernel_overlap/) | [kernel-overlap](../results/kernel-overlap/) |
| NCU/환경 제약·초기 최적화 탐색 | [진단 묶음](../diagnostics/) | [nsight-compute](../results/nsight-compute/), [optimization-sweep](../results/optimization-sweep/) |
| ROS/컨테이너·배포·EOS 검증 | [ROS2](../ros2/), [K8s](../k8s/) | [qwen-eos](../results/qwen-eos/), [k8s-serving](../results/k8s-serving/) |

[최종 성능 표](submission/BURST_TABLES.ko.md) · [보고서](TECHNICAL_REPORT.ko.md) · [그림 데이터](figures/burst-request-p95-before-after.json)
