# ROS 2 기본 지연시간 측정

## 실행 조건

- Qwen3.5-9B BF16/SDPA/FLA, YOLO26l FP16, imgsz640/batch1/rect=False.
- 각 Node의 기존 FIFO8 / Worker1 / UUID별 결과 토픽 유지.
- 동일 GB10 공유 슬롯2, SM/MPS 최적화 없음. CPU/RAM hard limit 없음.
- 부하는 모델별 closed-loop C1. 응답을 받으면 다음 요청을 전송한다.
- ROS 초기 발견은 제외하되 요청별 결과 publisher 발견 지연은 E2E에 포함한다.
- 모델 API인 generate()/predict() 및 설치된 프레임워크 원본은 수정하지 않는다.
- 최초 1회 탐색적 측정이다. Qwen N30의 p95/p99는 표본이 작고,
  반복·순서 교차 실험을 하지 않았으므로 안정적 SLO나 인과적 병목 결론이 아니다.

## 다섯 조건

| 디렉터리 | Pod 상주 | 활성 요청 |
|---|---|---|
| 01-qwen-only | Qwen만 | Qwen30 |
| 02-yolo-only | YOLO만 | YOLO300 |
| 03-both-resident-qwen | 둘 다 | Qwen30 |
| 04-both-resident-yolo | 둘 다 | YOLO300 |
| 05-concurrent | 둘 다 | Qwen30 + Qwen 종료까지 YOLO 연속 요청(최소30) |

각 조건마다 모델별 워밍업5건 제외. Qwen 프롬프트5개 순환, 최대128 신규 토큰,
greedy/early EOS 허용. YOLO bus.jpg/zidane.jpg 순환. 입력 해시와 실제 토큰 수 저장.
동시 조건에서 YOLO 완료 시점의 짧은 tail과 Qwen 윈도우 차이를 공개한다.
실제 달성 요청률은 조건별로 달라질 수 있으므로 고정 도착률 부하 실험이 아니다.
모든 측정 후 두 Deployment를 replicas1로 유지한다.

## 지표 정의

- request_e2e_ms: 준비된 입력의 JSON 직렬화·publish 직전 → UUID 응답 parse 완료.
- queue_wait_ms: 서버 callback에서 큐 삽입 직전 → Worker dequeue 직후.
- processing_ms: 기존 범위 유지(요청 파싱부터 추론·결과 변환 완료).
- worker_busy_ms: dequeue 이후 결과 publisher 연결/전송/ACK까지 점유한 시간.
- result_discovery_ms: 새 결과 publisher가 해당 reader를 찾는 시간.
- publish_call_ms: publish API 반환시간. 네트워크 전달 완료시간이 아니다.
- ack_wait_ms: DDS ACK 대기. 클라이언트 수신 이후 완료할 수 있어 E2E에 더하지 않는다.
- transport_client_residual_ms: E2E에서 서버 callback→publish 직전 추정 구간을 뺀
  잔여시간. 송수신·executor·클라이언트 처리가 섞이며 순수 네트워크 시간이 아니다.
  작은 경계 계측 오차가 있을 수 있으며 음수는 보존·flag 처리한다.

YOLO:
- image_decode_ms: base64, JPEG/PNG, RGB 변환.
- predict_wall_ms: 원본 predict 전체.
- yolo_preprocess_ms/inference_ms/postprocess_ms: result.speed 제공 값.
  설치 버전의 Profile이 accelerator를 동기화한 wall time이다.
  H2D가 전처리 안에 포함되므로 중복 합산하지 않는다.
- result_extract_ms: 검출값 CPU 변환·응답 구성.
- predict_overhead_ms는 전체와 내부 단계 합의 차이일 뿐 특정 원인의 직접 증거가 아니다.
- YOLO26 후처리를 무조건 NMS라 부르지 않는다.

Qwen:
- template_tokenize_ms / input_transfer_ms / generate_wall_ms / output_decode_ms.
- generate는 CPU 생성 제어+Prefill+Decode를 포함한다.
- TokenClock은 공식 streamer.put에서 첫 prompt 전달을 제외하고 출력 시각만 저장한다.
- generate_ttft_ms: generate 진입 → 첫 출력 토큰 관측.
- server_ttft_ms: 서버 callback → 첫 출력 토큰 관측.
- tpot_ms: 첫→마지막 출력 토큰 시간/(N-1). N<=1이면 null.
- itl_ms: 인접 출력 토큰 관측 간격. EOS가 생성되면 출력 토큰 수/시간에 포함한다.
- 토큰 수신 callback은 CPU에서 관측된 시각이며 순수 GPU 커널 시간은 아니다.
- ROS는 최종 응답만 보내므로 client TTFT가 아니다. TTFT와 Prefill도 동일하지 않다.
- 정확한 Prefill/Decode GPU hook 계측은 이번 기본 측정에 도입하지 않는다.

토큰별 synchronize/출력/파일쓰기 없음. generate 종료 시 기존 완료 경계 확인을 유지한다.
워밍업 뒤 기본 계측과 토큰 계측을 같은 입력으로 6쌍 교차 비교한다(출력64).
출력 문자열 동일성 및 관측 토큰 수를 확인한다. paired generate 시간 비율 차이의
중앙값이 5% 초과이면 본 측정은 basic, 그 이하면 tokens로 고정한다.
이 비교는 완전한 계측 OFF 대비가 아니며, 공통 타이머/로그 비용은 평가하지 않는다.

## 파일과 재현

- bench_ros2.py: 지속 ROS Node, 독립 C1, 원시 requests.jsonl 및 manifest.json
- aggregate_latency.py: 평균/linear p50·p95·p99, 처리량, 실패율
- join_server_timings.py: UUID로 전송 후 서버 로그 결합, 원시 기록 별도 보존
- monitor_host.py: 1초 간격 CPU/RAM/GPU util/온도/전력. GB10 메모리 N/A는 그대로 보존.
- run_five_phases.sh: Spark에서만 실행. 지정 배포 이미지로 전환하고 모델별 scale 조작.
- watch_run.py: 로컬에서 원격 장기 실행 상태 확인, 환경변수 기반 Slack 실패/완료 알림.

예:
```bash
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-ros2
python3 benchmark/bench_ros2.py --models qwen --output ~/cj-latency/example-new     --samples 30 --warmup 5 --max-new-tokens 128 --timing-mode tokens
```

출력 디렉터리가 이미 존재하면 덮어쓰지 않고 실패한다.
일반 request_qwen.py/request_yolo.py도 client_timings_ms를 선택적 결과 JSON에 포함한다.
YOLO CLI는 이미지 저장시간을 별도로 기록하며, benchmark에서는 이미지를 저장하지 않는다.

실패·타임아웃을 성공 latency에 섞지 않되 시도 수 분모에는 남긴다.
실행이 중간 실패한 경우 manifest/state=FAIL이므로 완성된 조건과 섞지 않는다.
