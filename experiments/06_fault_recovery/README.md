# 06 · IPC 운영 장애와 유휴 Node 복구

[실험 인덱스](../../docs/EXPERIMENT_INDEX.ko.md) · 문서 탐색용이며 소스·원시 자료를 복제하지 않는다.

## Objective

성능 개선과 별도로 실제 통신 장애 대응 및 제한된 프로세스 재시작 동작을 기록한다.

## Hypothesis

Pod Ready만으로 ROS 요청 처리 가능성을 보장하지 않는다. 유휴 Node 프로세스 종료 후 기본 Kubernetes 재시작이 서비스를 회복하는지 확인한다.

## Environment

IPC 사례는 당시 일반 서빙 환경의 운영 관측. 정량 SIGKILL은 별도의 native595/CUDART13.1/static8/40 실험이다.

## Workload

IPC: 로그아웃 후 ROS 요청/공유메모리 생존 확인. 정량 실험: YOLO CUDA 유휴·빈 큐 barrier 확인 후 전체 Node 프로세스 SIGKILL, 독립 Pod UID3개/각1회. Qwen 요청 관찰 병행.

## Configuration

기본 Kubernetes 재시작 정책. Worker는 스레드이므로 Worker만 kill한 실험이 아니다. MPS server/Qwen PID와 restart count 관찰. [supervisor](../../diagnostics/fault_idle/resource_supervisor.py).

## Methodology

IPC 장애는 processing_started 부재와 deleted FastDDS shm 증거를 조사하고 사용자 linger 활성화/Pod 재생성 후 복구, SSH 세션 없는15초·45초 후 재검증. 정량 장애는 [controller](../../diagnostics/fault_idle/controller.py)의 idle gate 후 monotonic fault→응답 시각과 polling 상태를 따로 기록한다.

## Metrics

fault→첫 유효 응답, 관측된 감지/container 시작/Ready 시각, Qwen 응답, MPS/PID 유지. polling Ready 관측은 첫 응답 시각보다 늦을 수 있다.

## Results

IPC 사례는 linger 조치 후 요청 성공을 확인했지만 정확한 발생시각이 없어 MTTR을 산출하지 않는다. 유휴 SIGKILL3회의 첫 유효 응답 평균4.390초, 범위4.163~4.504초. 각 restart1/exit137, MPS server와 Qwen host PID 유지. [정량 JSON](../../results/fault-idle/20261110-v1/analysis/summary.json).

## Analysis

IPC 수명·실제 요청 health를 Ready와 별도로 확인해야 한다. 정량 결과는 유휴 프로세스 재시작 경로의 관측이며 GPU 실행 중 fault tolerance와 구별한다.

## Limitations

in-flight CUDA 장애, queue persistence, retry/idempotency, warm standby/HA, MPS 공통 장애를 입증하지 않는다. 표본3개이며 보편적 MTTR/SLA가 아니다. IPC 원인 증거와 수명 정책의 일치가 모든 장애 원인 확정이라는 뜻도 아니다.

## Artifacts

[IPC 원본 기록](../../results/green-context/README.ko.md) · [linger 운영 설정](../../k8s/mps-green/README.ko.md) · [정량 원시 묶음](../../results/fault-idle/20261110-v1/) · [CSV](../../results/fault-idle/20261110-v1/analysis/trials.csv) · [idle ack](../../results/fault-idle/20261110-v1/control/) · [그림](../../results/fault-idle/20261110-v1/plots/recovery-timeline.svg) · [분석 코드](../../diagnostics/fault_idle/analyze.py)
