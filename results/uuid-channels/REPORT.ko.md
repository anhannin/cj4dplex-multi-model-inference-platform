# UUID별 ROS 결과 채널 검증

## 구현

- 요청은 고정 /qwen/request,/yolo/request String JSON, 결과는 /MODEL/result/r_UUID다.
- 모델별 독립 FIFO와 원본 SDK 호출을 유지했다. Service/Action은 사용하지 않는다.
- request_qwen.py --text는 답변 출력 후 종료한다. request_yolo.py --image [--output]은 클라이언트에서 박스를 그려 저장 후 종료한다.
- YOLO 요청은 ID를 담기 위해 CompressedImage에서 JSON/base64로 변경했다. 전송량 증가를 감수한 최소 메시지 구현이며 원본 frame_id를 ID로 오용하지 않는다.

## 실제 검증

- 네이티브 Spark CLI4개 동시 실행: Qwen2 + 이미지2. 고유 ID4개, 응답 혼합0, 결과 이미지2개.
- 단일 클라이언트 최종 실행도 Qwen/YOLO 각각 성공했다.
- callback enqueue/FIFO/직렬 처리, 모델 간 처리 구간 중첩과 모델 로딩1회를 확인했다.
- 결과 writer가 match/ACK 후 정리돼 클라이언트 종료 후 해당 UUID publisher 수가0임을 확인했다.
- 입력 파일 hash 보존, annotation 크기/실제 픽셀 변경, 원본 덮어쓰기 방지 검사.
- CPU46개, Ruff, Python compile, Bash 구문, 두 이미지 pip check 통과.

| 클라이언트 | Sequence | Queue ms | 처리 ms |
|---|---:|---:|---:|
| q1 | 3 | 0.27 | 11486.28 |
| q2 | 4 | 7940.03 | 2875.46 |
| y1 | 3 | 0.25 | 34.95 |
| y2 | 4 | 0.81 | 33.90 |

## 발견한 문제와 수정

첫 동시 시험에서 관찰용 reader가 모델 reader보다 먼저 match하면 client가 일찍 publish해 모델이 요청 한 건을 놓쳤다. 클라이언트 writer가 reliable TRANSIENT_LOCAL depth1로 메시지를 보관하고 모델 reader도 TRANSIENT_LOCAL을 사용하도록 맞췄다. 애플리케이션 재전송을 임의 추가하거나 모델 코드를 패치하지 않았다.
시험용 observer도 이 history를 확인하려면 같은 transient durability가 필요했다. observer의 volatile 설정 때문에 실제 정상 결과를 실패로 판정한 시험 도구도 수정했다. 이전 시도 로그는 보존했다.

## 범위

단회 기능 검증이며 정확도·성능 개선·SLO·보안·복구를 증명하지 않는다. UUID Topic은 채널 구분이며 인증이 아니다. 결과 ACK는 client의 파일 저장 완료가 아니라 DDS 수신 확인이다. 서버 재시작을 넘는 exactly-once나 지속 저장은 제공하지 않는다.
이전 v1 CompressedImage/공통 result 인터페이스와 호환되지 않는다. 기존 서버 컨테이너는 v1 이름으로 보존하고 현재 UUID 버전을 상주시켰다.

## 증거

concurrent/summary.json, single/*-final.json, 이미지PNG, stdout/stderr, qwen-uuid-final.log/yolo-uuid-final.log, uuid-deployment.txt, uuid-pip-check-*.txt, unit-tests.log, audit.json, deployed-code/에 저장했다. 실제 배포 파일과 로컬 파일 SHA-256이 일치한다.
사용 방법: [clients/README.md](../../clients/README.md).
