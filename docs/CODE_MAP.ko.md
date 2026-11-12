# 코드 탐색 지도

## 먼저 읽을 자료

- 동결 당시 루트 README 원문: `docs/history/baseline-root-README.md` (제출 안내용 현재 루트 README와 구별).
- 원본 동결/해시/외부 이미지: `baseline/README.ko.md`, `baseline/MANIFEST.json`, `baseline/FILES.sha256`.
- 최종 측정: `results/static-eval/README.ko.md`, `results/sustained/README.ko.md`, `results/fault-idle/README.ko.md`.
- 재현 경계와 검증 명령: [REPRODUCIBILITY.ko.md](REPRODUCIBILITY.ko.md).
- 일반 MPS+Green 서빙/복원: `k8s/mps-green/README.ko.md`. 최종 native-static 실험 구성과 동일하지 않다.

## 요청이 실행되는 경로

```text
clients/request_qwen.py → /qwen/request → ros2/qwen_node.py → 독립 FIFO/Worker → generate()
clients/request_yolo.py → /yolo/request → ros2/yolo_node.py → 독립 FIFO/Worker → predict()
각 Node → /{qwen,yolo}/result/r_UUID → 요청한 클라이언트
```

`std_msgs/msg/String` JSON 프로토콜이다. 각 모델은 별도 프로세스/큐/추론 스레드를 가지며 공통 스케줄러나 모델 간 공유 FIFO가 없다. 기본 큐는 대기8+실행1, 실험 생성본은 별도 용량을 쓴다. UUID 결과 토픽을 먼저 구독하고 요청을 발행한다. publisher 발견/ACK는 실제 E2E/worker 점유에 영향을 주지만 GPU kernel 시간과 같지 않다. 상세 계약은 `ros2/README.md`, `clients/README.md`다.

## 파일별 책임

| 영역 | 주요 파일 | 역할/주의 |
|---|---|---|
| ROS 서버 | `ros2/qwen_node.py`, `ros2/yolo_node.py` | 원본 모델 호출, 입력 검증, FIFO, UUID 결과 publisher와 수명 관리 |
| ROS 클라이언트 | `clients/request_qwen.py`, `clients/request_yolo.py` | 요청/응답 매칭, timeout, 선택 결과 JSON 및 YOLO 이미지 저장 |
| 이미지 빌드 | `containers/qwen/Dockerfile.ros`, `containers/yolo/Dockerfile.ros`, `containers/ros2/install_ros.sh` | 기존 모델 부모 이미지에 ROS 설치. 가중치를 Git에 포함하지 않음 |
| 개발/실행 | `scripts/start_ros2.sh` | Docker 실행 경로. Kubernetes 실험 controller와 별개 |
| Kubernetes | `k8s/serving/{qwen,yolo}.json`, `deploy.sh`, `rollback.sh`, `gpu-sharing.json` | 배포/볼륨/프로브/공유 GPU 슬롯. 동결 실제 배포 사본은 `baseline/deployment/` |
| 초기 측정 | `benchmark/bench_ros2.py`, `run_five_phases.sh` | C1 다섯 조건 제어 및 원시 요청 기록; 실제 Deployment scale 조작 있음 |
| 기본 집계 | `benchmark/aggregate_latency.py`, `join_server_timings.py` | latency 분포/실패 분모 및 UUID 로그 결합. 집계는 출력 파일을 씀 |
| 최적화 탐색 | `optimization/run_sweep.py`, `overlays.py`, `compare.py`, `pool_results.py` | 이전 탐색/후보 비교. 최종 static/sustained 판정과 혼합하지 않음 |
| Green 어댑터 | `diagnostics/green_context/green_bridge.cu`, `build.sh` | CUDA Green API native binding. 환경별 빌드 필요 |
| 일반 MPS+Green | `diagnostics/mps_concurrency/{serving,deploy,overlay,runtime}.py` | 서빙 생성, socket/환경 연결, 배포 및 복원 |
| native static | `diagnostics/mps_static/{plan,config,generate}.py`, `eval_runner.py`, `native_query.cu` | 7조건×5회 계획, 실제 partition ID/SM/runtime 검증; Green과 별개 |
| static 결과 분석 | `diagnostics/mps_static/{analyze_eval,summary_math}.py` | 원시 감사/조건별 분포/서술적 tie-band 순위 |
| 지속 부하 | `diagnostics/sustained/{protocol,client,controller,analysis,report}.py` | pilot 요청률 고정, C1+open-loop 생성,40회 제어, 실행별 p95 SLO 판정 |
| 유휴 장애 | `diagnostics/fault_idle/{generate,controller,resource_supervisor,metrics,analyze}.py` | 실제 worker idle 동기화, 정확한 PID 검증, SIGKILL/재시작 관측/독립 감사 |
| 프로파일 진단 | `diagnostics/nsight/`, `kernel_overlap/`, `sm_sweep/`, `green_e2e/`, `green_burst/` | Nsight/SM/동시성 진단. 프로파일링 결과를 비계측 성능 표본과 합치지 않음 |
| CPU 회귀 | `tests/test_mps_static.py`, `test_sustained*.py`, `test_fault_idle.py`, 기타 `tests/test_*.py` | 계획/생성/통계/프로토콜/안전 경계 검사. 실제 ROS 통합은 `tests/ros2/` |

## 원본 소스와 실행 사본을 혼동하지 않기

- `baseline/container-code/{qwen,yolo}/app/`: 동결 시 실제 컨테이너에서 추출한 프로젝트 코드. 원본 보존 대상으로 취급한다.
- `baseline/host-code/`: 동결 당시 호스트 클라이언트/측정기/Dockerfile 스냅샷.
- `results/<실험>/<run>/src/`: 실험 당시에 복사·재명명한 helper와 generated node 묶음. `base_runner`, `control_runner`, `stage_metrics` 같은 import는 이 묶음 안에서 해결한다. 루트 diagnostics만 복사하면 실행 준비가 끝나는 것이 아니다.
- 루트 `container_code/`: 과거 개발 환경의 라이브러리 열람용 별도 스냅샷이다. 직접 작성한 모델 알고리즘이나 동결 실행본으로 취급하지 않는다.
- `results/`의 `requests.jsonl`/`final-requests.jsonl`, `logs/`, `metadata/`, `verification/`는 관측 근거다. 분석 재실행 시 임시 사본을 사용한다.

## 제거한 실행 경로

활성트리의 `api/`, `serving/`, `clients/http/`, HTTP전용Dockerfile·실행기·테스트와초기preflight/sleep개발launcher를제거했다. 결과가끝나길기다리는one-offwatch/수집wrapper도제거했다. `k8s/serving/`는이름과달리ROS배포이므로유지한다.

삭제된실행기의재현에필요한직접명령은[REPRO_COMMANDS](REPRO_COMMANDS.ko.md)에남겼다. baseline/과results/의당시실행source사본은활성코드가아닌증거로보존한다. 필요한Green/MPSgenerator/runtime/helper를최종실행이미Green미사용이라는이유로삭제하지않는다. 전체목록은[실행파일정리](EXECUTABLE_CLEANUP.ko.md).
