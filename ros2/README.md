# ROS 2 모델 노드 v2 — UUID별 결과 채널

서버 코드는 `qwen_node.py`, `yolo_node.py` 두 개다. 모델마다 독립 FIFO/추론 스레드가 있고,
원본 generate()/predict()를 직접 호출한다. Service/Action/공통 모드/Backend 래퍼는 없다.

## Spark에서 요청

```bash
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-ros2/clients
python3 request_qwen.py --text "GPU 자원 경합을 설명해 줘."
python3 request_yolo.py --image ~/cj-containers/assets/bus.jpg --output ~/bus_detected.png
```

각 프로세스는 `r_`+UUID를 생성하고 자기 결과 토픽을 먼저 구독한다.
Qwen은 답변만 출력하고 종료, YOLO는 검출 박스·라벨을 원본에 그려 새 파일로 저장하고 경로를 출력한다.
별도 echo 터미널이 필요 없다. `--timeout` 기본300초, `--result-json`으로 원시 결과를 선택 저장할 수 있다.
[상세 클라이언트 안내](../clients/README.md).

## 프로토콜

|모델|고정 입력 Topic|요청 String JSON|개별 결과 Topic|
|---|---|---|---|
|Qwen|/qwen/request|request_id,text,max_new_tokens|/qwen/result/r_UUID|
|YOLO|/yolo/request|request_id,image_base64|/yolo/result/r_UUID|

입력·결과 모두 std_msgs/msg/String이다. **v1 CompressedImage 입력·공통 result 구독과 호환되지 않는다.**
이미지는 base64로 보내므로 전송량이 약33% 늘어난다. 사용자 정의 msg/colcon 빌드는 필요 없다.

- 요청 writer: reliable TRANSIENT_LOCAL depth1, 서버 reader: TRANSIENT_LOCAL depth32.
  client가 기다리는 동안 요청1개를 보관해 모델 reader가 늦게 match해도 받을 수 있게 한다.
- 앱 Queue는 별도 FIFO8개 + 실행1개다. callback은 raw 메시지 enqueue만 하고 Full이면 경고·새 요청 거절.
- Worker에서 UUID와 입력을 검사하고 모델을 호출한다. 잘못된 UUID로 임의 Topic을 만들지 않는다.
- 결과 writer는 매 요청 생성, 구독자 match를 기본5초 대기, publish 후 reliable ACK를 최대2초 대기,
  finally에서 destroy한다. ACK는 DDS 수신 확인이지 출력/파일 저장 완료 확인이 아니다.
- UUID는 요청별 채널 분리 수단이며 인증·암호화가 아니다. ROS Domain42/localhost 전용이다.
- 앱 재시도/영속 Queue/재시작을 넘는 exactly-once/추론 취소/장애 복구는 없다.

Qwen 최대 입력32768문자·template 포함2048토큰은 유지한다. 출력은 기본 EOS까지 생성하며 모델 문맥 한계를 넘지 않는다. BF16/SDPA.
YOLO는 JPEG/PNG 최대10MiB·16M pixels, CUDA FP16/640/Batch1. 박스는 원본 좌표다.
queue_wait_ms는 callback enqueue~dequeue, processing_ms는 입력 변환/추론/결과 준비까지이며 DDS 전송은 제외한다.
결과 전송·발견 비용이 있으므로 순수 GPU 추론 시간이나 고빈도 프레임 최적화 구조로 해석하면 안 된다.

## 현재 배포

- `cj-qwen-ros:9b-eos` / 컨테이너 `cj-qwen-ros`
- `cj-yolo-ros:26l-uuid` / 컨테이너 `cj-yolo-ros`
- 기존 고정 결과 v1은 `cj-qwen-ros-v1`, `cj-yolo-ros-v1`로 보존·정지했다.
- 기존 API는 정지 상태를 유지하고 dev 컨테이너는 유지했다.
- 호스트 ROS 환경은 이미 설치된 Jazzy를 사용한다. 이번 변경에 새 방화벽·드라이버 변경은 없다.

빌드는 기존 Dockerfile.ros와 `scripts/start_ros2.sh`를 사용한다. 모델·데이터는 read-only 마운트한다.
처음 구축할 때 model parent 이미지가 필요하며 기존 컨테이너를 자동 덮어쓰지 않는다.
`queue_capacity`, `result_timeout`(초, float), Qwen `max_new_tokens`는 시작 ROS parameter다.
프로세스마다 모델을 한 번 로딩하고 정상 종료는 진행 중인 GPU 작업이 끝나길 기다린다.

## 검증

`tests/ros2/test_uuid_clients.py`로 실제 Spark 호스트의 독립 CLI4개를 동시에 실행했다.
UUID4개/잘못 연결된 응답0/이미지 저장2개/원본 보존/결과 writer 정리를 검사했다.
별도 CPU 테스트는 callback FIFO, Publisher 수명, UUID 필터·검사와 파일 저장을 검사한다.
증거: `results/uuid-channels/`. v1 테스트 스크립트·이전 결과는 역사 기록으로 유지한다.
사용/검토 ZIP: `downloads/ros2_uuid_clients.zip`.

## Qwen 출력 길이 변경 (2026-11-03)

ROS Qwen 클라이언트에서 `--max-new-tokens`를 생략하면 128/512 등의 운영 상한을 넣지 않는다.
서버의 기본 ROS parameter `max_new_tokens=0`은 EOS/남은 모델 문맥까지 생성한다는 의미다.
현재 실제 모델 config의 문맥은262144토큰이며 입력 길이만큼을 뺀 값을 generate 상한으로 사용한다.
Transformers의 max_new_tokens를 단순히 생략해 기본 max_length로 잘리는 일을 피한다.
명시적으로 `--max-new-tokens 4096`처럼 양의 정수를 지정할 수 있으며 임의의512 상한은 없다.
단, 모델의 남은 문맥보다 큰 명시값은 거절한다. 입력 길이 제한은 바꾸지 않았다.
응답 JSON에 finish_reason(eos/length), generation_mode, effective_max_new_tokens, context_limit을 추가했다.
이 변경은 ROS Qwen에만 적용했으며 이전 FastAPI/HTTP 클라이언트의 정책은 변경하지 않았다.
모델이 EOS를 내지 않으면 작업이 매우 길어지거나 메모리 부족이 날 수 있고 Queue 대기도 늘어난다.
클라이언트 timeout 기본300초는 생성 토큰 상한이 아니며 `--timeout 1800` 등으로 조절한다.
클라이언트가 먼저 나가도 실행 중 추론을 자동 취소하지 않는다.
