# 독립 ROS 2 모델 노드 구현·검증

## 결과

- 배포 Python 코드는 `ros2/qwen_node.py`, `ros2/yolo_node.py` 두 개로 분리했다.
- 공통 모드/Backend/추론 래퍼 없이 각 파일에서 원본 model.generate()/model.predict()를 직접 호출한다.
- callback은 원본 메시지와 sequence/time을 해당 노드의 FIFO에 enqueue할 뿐이다.
- 두 노드는 별도 프로세스/Queue/추론 스레드를 가지며 다른 모델의 상태를 확인하지 않는다.
- 모델 로딩1회, callback/추론 분리, 실제 ROS DDS 토픽 송수신을 확인했다.

## 실제 요청 결과

| 모델 | sequence | 상태 | 대기 ms | 처리 ms |
|---|---:|---|---:|---:|
| qwen | 6 | ok | 0.17 | 11460.26 |
| qwen | 7 | ok | 10954.28 | 2863.72 |
| qwen | 8 | ok | 13818.41 | 1436.10 |
| qwen | 9 | error | 0.16 | 0.38 |
| yolo | 1 | ok | 0.51 | 62.05 |
| yolo | 2 | ok | 63.21 | 36.22 |
| yolo | 3 | error | 100.09 | 20.98 |
| qwen (ros2 CLI) | 10 | ok | 0.15 | 458.83 |

- 정상6건(Qwen JSON3 + 실제 ros2 topic pub/echo1 + JPEG 이미지2)이 실제 모델 결과를 반환했다.
- 빈 프롬프트와 손상 이미지는 예상 오류 결과2건을 반환했고 Queue consumer는 다음 요청을 처리했다.
- Qwen 두 번째/세 번째 요청은 약10.95초/13.82초 대기해 FIFO 처리를 확인했다.
- Qwen 첫 작업이 약11.46초 처리되는 동안 YOLO 작업이 완료됐다. 로그 시각의 처리 구간 중첩을 audit.json에 보존했다.
- FIFO는 callback에서 큐에 넣은 순서다. middleware 지연/다중 publisher의 전체 전송 순서나 무손실 처리를 보장하지 않는다.
- 단회 기능 검증이며 SLO/정확도/성능 개선을 입증한 결과가 아니다. 첫 실행은 JIT/autotuning을 포함할 수 있다.

## 환경과 실제 배포

- 기존 NVIDIA 모델 이미지에 ROS2 Jazzy ros-base/std_msgs/sensor_msgs를 설치했다(Ubuntu24.04,ARM64,Python3.12).
- Qwen은 BF16/SDPA 및 외부 causal-conv1d/FLA dispatcher 연결을 확인했다. YOLO 실제 실행 Backend는 CUDA FP16이다.
- 통신은 std_msgs/String, sensor_msgs/CompressedImage이며 사용자 정의 msg나 colcon 빌드가 없다.
- ROS_DOMAIN_ID42, localhost-only discovery, host network/IPC. 호스트에 ROS를 설치하거나 방화벽을 바꾸지 않았다.
- `cj-qwen-ros`, `cj-yolo-ros`가 상주 실행 중. 기존 FastAPI 두 컨테이너는 보존·중지했고 기존 개발 컨테이너는 유지했다.
- Kubernetes 모델 배포/GPU 공유 설정/복구/재시도/Action/Service는 구현하지 않았다.

## 시험 중 수정

- 손상 이미지 처리 시 Ultralytics가 공식 선택 codec pi-heif의 런타임 설치를 시도했다. 모델 코드 수정/검사 비활성화 대신 pi-heif1.4.0을 이미지 빌드 때 설치해 재시험했다.
- 첫 시도의 데이터는 live-first-attempt.json으로 보존하고, 최종 live-verified.json 및 현재 로그와 구분했다.
- 최종 로그에 reference fallback/Traceback/권한 오류가 없으며 두 이미지 pip check 통과.

## 검증·소스 증거

- CPU 테스트34개(기존29 + ROS 파일/콜백 계약5) 통과. ROS 계약 테스트는 ROS/GPU 없이 callback/AST를 검사한 것이며, 실제 ROS 검증은 별도 실험으로 수행했다.
- 실제 ROS 테스트 스크립트: tests/ros2/test_live_topics.py. 가짜 모델·HTTP bridge가 아닌 실제 DDS/실제 GPU 모델을 사용했다.
- ros-graph.txt: 노드/토픽, qwen.log/yolo.log: 모델 로딩·작업 순서/상태·시각.
- ros-versions-*.txt, deployment.txt, pip-check-*.txt: 실제 환경 기록.
- deployed-code/의 파일을 실행 컨테이너에서 다시 내려받아 로컬 소스와 SHA-256 일치를 확인했다.
- review-files-sha256.json 및 downloads/ros2_nodes.zip MANIFEST.json에 해시 보존.
- Ruff/compileall/Bash 구문 검사 통과. 장기 안정성/장애 복구/보안 감사를 수행한 것은 아니다.

사용 방법: [ROS2 노드 안내](../../ros2/README.md).
