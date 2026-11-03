# 요청 한 건을 보내고 자기 결과만 받는 ROS 2 클라이언트

Spark에서 실행한다. 새 SSH 터미널은 Jazzy 환경이 자동 설정된다.
기존 터미널이라면 먼저:

```bash
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-ros2/clients
```

## Qwen

```bash
python3 request_qwen.py --text "GPU 자원 경합을 설명해 줘."
python3 request_qwen.py --text "한 문장으로 요약해 줘." --max-new-tokens 64 --timeout 300
```

UUID를 생성해 결과 채널을 먼저 구독한 뒤 요청한다. 자기 결과의 답변만 stdout으로 출력하고0으로 종료한다.
Python에서 `request_qwen(text, max_new_tokens=None, timeout=300)`를 호출하면 결과 dict를 반환한다.

## YOLO

```bash
python3 request_yolo.py --image ~/cj-containers/assets/bus.jpg --output ~/bus_detected.png
```

이미지를 보내고 검출 결과를 받으면 **클라이언트가 원본 이미지에 박스/라벨을 그려** 저장한다.
저장 경로를 출력하고0으로 종료한다. 서버가 별도의 결과 이미지를 전송하는 구조는 아니다.
`--output`을 생략하면 원본 옆에 `<stem>_detected_<request_id>.png`를 만든다.
입력/기존 결과 파일을 덮어쓰지 않는다. 요청이 끝날 때까지 입력 파일을 바꾸지 않는다.
Python 함수 `request_yolo(image_path, timeout=300)`는 결과 dict를,
`save_result_image(source, output, reply)`는 저장한 경로를 반환한다.

## 공통

- `--result-json /new/path.json`: 선택적으로 원시 응답·ID·대기/처리시간 저장(기존 파일 덮어쓰기 금지).
- 기본 timeout300초, discovery + Queue 대기 + 추론 + 응답 수신을 포함한다.
- 오류/timeout/저장 실패는 stderr 메시지와 비정상 종료 코드로 알린다.
- 서로 다른 프로세스에서 동시에 실행해도 UUID별 결과 채널이 다르다.
- 현재는 Spark 내부 localhost/Domain42용이다. 별도 PC의 LAN 통신은 설정하지 않았다.
- Python3.12/rclpy/std_msgs, YOLO 저장은 Pillow 필요. Docker 클라이언트는 필요 없다.
- 예전 HTTP 클라이언트는 `clients/http/`에 보존했다.

## 전송 형식 v2

```text
고정 /qwen/request (String JSON: request_id, text, max_new_tokens)
    → /qwen/result/r_<UUID> (String JSON)

고정 /yolo/request (String JSON: request_id, image_base64)
    → /yolo/result/r_<UUID> (String JSON)
```

`request_id`는 `r_` + 소문자16진수32자리다. UUID가 숫자로 시작하더라도 유효한 ROS 이름이 되게 한다.
서버는 ID를 검증해 자기 result prefix 안으로만 응답한다. 와일드카드 구독은 사용하지 않는다.
클라이언트는 자기 토픽만 구독하고 응답 JSON의 ID도 다시 확인한다. 인증/암호화 보장은 아니다.

YOLO v1의 CompressedImage 요청과 고정 result 토픽은 이 프로토콜과 호환되지 않는다.
사용자 정의 msg/colcon 빌드를 피하려 JSON/base64를 선택했으며 이미지 전송량은 원본 대비 약33% 증가한다.
고빈도 연속 프레임에 최적화된 전송 형식이라고 주장하지 않는다.

요청 writer는 reliable TRANSIENT_LOCAL depth1로 응답 대기 동안 요청1개를 유지하고,
서버 request reader도 TRANSIENT_LOCAL depth32다. 다른 관찰용 reader가 먼저 연결돼도
모델 reader가 늦게 match하면 요청을 받을 수 있게 한다. 애플리케이션 재전송/영속 Queue는 없다.
서버/클라이언트 재시작을 넘는 exactly-once 처리를 보장하지 않는다.

서버 결과 writer는 매 요청 생성해 구독자 연결을 제한된 시간(기본5초) 기다린 후 보내고,
reliable ACK를 최대2초 기다린 뒤 destroy한다. ACK는 DDS 수신 확인이며 클라이언트 파일 저장 완료 확인은 아니다.
클라이언트가 timeout으로 나가도 이미 실행한 추론을 강제로 중단하지 않는다.

## 기존 서버 특성 유지

노드 파일은 `ros2/qwen_node.py`, `ros2/yolo_node.py`로 독립적이다.
각 callback은 raw String을 자기 FIFO에 넣기만 하고, 단일 추론 worker에서 원본 generate/predict를 호출한다.
기본 대기8개 + 실행1개이며 Queue full이면 새 요청을 넣지 않고 경고한다(해당 클라이언트는 timeout할 수 있음).
모델 간 상태 확인/공통 Queue/글로벌 Lock/Service/Action은 없다.
현재 서버 이미지는 `cj-qwen-ros:9b-eos`, `cj-yolo-ros:26l-uuid`다.
기존 v1 컨테이너는 `cj-qwen-ros-v1`, `cj-yolo-ros-v1`로 보존·중지했다.

## 검증 및 제한

CPU 테스트: UUID 필터, 잘못된 ID 차단, 결과 writer match/ACK/정리, 이미지 저장/원본 보존.
실제 Spark 테스트: 단일 요청 + 복수 네이티브 클라이언트 동시 실행, 다른 응답 혼합 없음,
각 UUID별 publisher 정리, 입력별 이미지 저장과 원본 hash 보존을 확인한다.
최종 증거는 `results/uuid-channels/` 참조. 단회 기능 시험이며 보안/SLO/정확도/성능 개선 증거가 아니다.

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
