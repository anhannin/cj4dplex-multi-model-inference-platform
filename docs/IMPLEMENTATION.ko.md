# 구현 범위와 근거

이 문서는 **코드 구현**, **보존된 실행 관측**, **미구현 제안**을 구별한다. 최종 성능 근거는 고정 작업량 Burst 비교이며 지속 부하 실험은 별도 탐색 자료다. 실제 GPU 재실행 없이 문서와 소스/실행 사본을 대조했다.

## 구현 매트릭스

| 영역 | 구현한 것 / 근거 소스 | 관측과 한계 |
|---|---|---|
| ROS 요청·응답 | `clients/request_qwen.py`, `clients/request_yolo.py`, `ros2/qwen_node.py`, `ros2/yolo_node.py`: String JSON, `r_`+UUID, 결과 토픽 선구독과 ID 검사 | 입력은 `/qwen/request`, `/yolo/request`, 결과는 `/<model>/result/<id>`. UUID는 인증 경계가 아니다. |
| 독립 FIFO | 각 node의 `queue.Queue`, callback의 `put_nowait`, 모델별 단일 inference worker | 기본 대기8+실행1. 큐 포화 시 `queue_full` 로그이며 생산자 재시도/입장제어를 갖춘 고급 backpressure가 아니다. |
| 원본 모델 호출 | Qwen tokenizer→`generate`→decode, YOLO image decode→`predict`→boxes | 프레임워크/모델 알고리즘을 새로 구현한 것이 아니다. Qwen 기본 `max_new_tokens=0`은 EOS 경로다. |
| 결과 수명 | node의 일회성 UUID publisher, discovery/ACK 대기와 정리 | 이 대기도 worker 점유/E2E에 포함될 수 있다. GPU kernel 시간과 같지 않다. |
| 이미지·배포 | `containers/{qwen,yolo}/Dockerfile.ros`, `k8s/serving/{qwen,yolo}.json` | 외부 frozen 이미지와 호스트 가중치/asset 필요. 새 self-contained 최종 이미지를 만들었다고 주장하지 않는다. |
| 일반 MPS+Green | `diagnostics/mps_concurrency/{serving,overlay,deploy,runtime}.py`, `diagnostics/green_context/green_bridge.cu` | 복원 서빙은 normal MPS+Green Q16/Y32, queue8. 최종 native-static 성능 조건과 다르다. |
| native MPS static | `diagnostics/mps_static/{plan,config,generate,eval_runner}.py` | control/일반 MPS/정적 8/40·16/32·24/24·32/16·40/8, 7조건×5회. 생성 node는 Green API를 실행하지 않는다. |
| 측정·감사 | `diagnostics/green_burst/generate.py`, `diagnostics/mps_static/{analyze_eval,summary_math}.py` | 요청 UUID, 단계 timestamp, CUDA Event span, membership/SM/runtime 검증. span은 순수 SM 실행시간 보장이 아니다. |
| 장애 | `diagnostics/fault_idle/{controller,resource_supervisor,metrics,analyze,qwen_monitor,yolo_probe}.py` | 자체 구현은 idle 동기화·PID 확인·SIGKILL 주입·실제 응답 probe·시간 분석이다. 프로세스 재시작 자체는 Kubernetes 기본 기능이다. |

## 구현하지 않은 것

- 자체 HA controller, 다중 노드 failover, durable queue/요청 재전송 및 exactly-once 보장.
- streaming 응답, batching/dynamic batching, 모델 간 전역 스케줄러, 동적 SM 재배분.
- GPU 메모리/장애 완전 격리, 외부 공개용 인증·인가, 기능적 hang를 검출하는 production liveness.
- readiness에 의한 ROS/DDS 요청 차단. PID marker는 모델 로드와 프로세스 생존만 확인한다.

## 실행 근거와 의존성

보존된 `results/static-eval/20261110-v1/verification/r1-static-q8-y40-warmup-deployment.json`의 실제 template은 frozen timing 이미지, `/experiment/src/*_burst_node.py`, queue16/512, domain74, CUDA13.1 host mount 및 opaque partition ID를 기록한다. 이 ID는 당시 할당 결과이며 재사용할 상수가 아니다.

`diagnostics/mps_static/generate.py` → `diagnostics/green_burst/generate.py` → `diagnostics/green_e2e/generate.py`의 생성 의존성은 Green off에서도 필요하다. `base_runner`, `control_runner`, `base_burst_generate` 등의 별칭은 당시 `results/<run>/src/` 묶음에서 해결한다. 최종 Green 미사용을 이유로 이 helper를 삭제하거나 개별 파일만 복사해 실행 가능한 것으로 간주하지 않는다.

관련 문서: [아키텍처](ARCHITECTURE.ko.md), [배포 모드](DEPLOYMENT_MODES.ko.md), [코드 지도](CODE_MAP.ko.md), [재현 경계](REPRODUCIBILITY.ko.md).
