> **역사 문서:** 아래는 이전 HTTP 탐색 기록이다. FastAPI 실행 코드·전용 Dockerfile·HTTP 테스트는 2026-11-12 제출 정리에서 제거했다. 실행 안내로 사용하지 말고 현재 ROS2 경로와 `CODE_MAP.ko.md`를 따른다. 원문 당시 코드는 동결 baseline 및 결과 source 스냅샷에 보존된다.

# 최소 FastAPI 모델 서빙

## 현재 상태

두 API는 구현·검증 완료 상태다. 이후 ROS 2 버전으로 전환하면서 현재 API 컨테이너는
**삭제하지 않고 중지**했다. 현재 실행 중인 모델은 `ros2/README.md`를 참고한다.

| 모델 | 이미지 | 컨테이너 | Spark 호스트 주소 |
|---|---|---|---|
| Qwen3.5-9B | `cj-qwen-api:9b-v1` | `cj-qwen-api` | `http://127.0.0.1:8001` |
| YOLO26l | `cj-yolo-api:26l-v1` | `cj-yolo-api` | `http://127.0.0.1:8002` |

기존 모델 이미지와 `cj-qwen-dev`, `cj-yolo-dev`는 유지했다.
이번 단계는 Docker HTTP 서빙이며 Kubernetes에 모델을 배포한 것이 아니다.

## 구조

```text
POST :8001/generate -> Qwen 전용 FIFO -> Qwen 추론 스레드 -> JSON 응답
POST :8002/detect   -> YOLO 전용 FIFO -> YOLO 추론 스레드 -> JSON 응답
```

- 컨테이너마다 Uvicorn 프로세스1, 상주 모델1, Queue1, 추론 consumer/thread1.
- 모델 로딩·가속 확인·워밍업이 끝나야 요청을 받는다. 요청마다 재로딩하지 않는다.
- Queue는 프로세스 메모리 안에 있으며, 모델 사이에 공유하는 상태/Lock/Queue/스케줄러가 없다.
- **한 모델 내에서는 순차 처리**, 두 모델의 추론 작업은 독립적으로 진행한다.
- FIFO는 **입력 검증을 마치고 해당 Queue에 들어간 순서**다. 이미지 크기/검증 시간이
  다를 수 있어 네트워크 연결 시작 순서와 반드시 같지는 않다. `sequence`가 enqueue 순서다.
  거절·취소된 요청 때문에 번호가 빠질 수 있다.
- 기본 Queue 용량은 **대기8개 + 실행 중1개**다. `QUEUE_CAPACITY` 환경변수로 변경한다.
  일반 동시 요청은 기다리며, 대기열이 꽉 찼을 때만429를 반환한다.
- HTTP 연결은 자기 결과가 나올 때까지 유지한다. job polling 방식이 아니다.
- 대기 중 클라이언트 연결이 끊기면 실행 전에 건너뛴다. 취소된 항목이 맨 앞에서 제거되기
  전까지 Queue 용량을 차지할 수 있다. 이미 시작한 GPU 추론은 강제로 중단하지 않는다.
- 요청이 없으면 추론하지 않고 GPU 가중치만 상주한다. 배치/스트리밍/대화 이력은 없다.

공통 Python 코드를 사용해도 Queue 객체와 모델은 각 프로세스에서 별개로 생성된다.
소프트웨어가 서로의 실행을 막지 않는다는 뜻이지, GPU 커널의 하드웨어 동시 실행이나
지연시간 격리를 보장한다는 뜻은 아니다. GPU 자원 경합은 그대로 발생할 수 있다.

## 로컬 PC에서 접속

Spark의 포트는 **127.0.0.1에만 공개**했다. LAN/인터넷에 직접 API를 열지 않았다.
로컬 PC에서 SSH 터널을 유지한다:

```bash
ssh -N -L 8001:127.0.0.1:8001 -L 8002:127.0.0.1:8002 avees@192.168.24.204
```

브라우저:
- Qwen: http://127.0.0.1:8001/docs
- YOLO: http://127.0.0.1:8002/docs

`/docs`의 Try it out으로 입력하거나 아래 클라이언트를 사용한다.
Swagger UI의 정적 파일은 기본적으로 외부 CDN을 사용하므로 브라우저 인터넷 연결이 필요할 수 있다.
Spark에 SSH 접속한 터미널에서는 터널 없이 같은 localhost 주소를 사용한다.

## Qwen 요청

```bash
python3 clients/http/request_qwen.py 'GPU 자원 경합을 한 문장으로 설명해 줘.' --max-new-tokens 64
```

```bash
curl -s http://127.0.0.1:8001/generate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Explain GPU resource contention briefly.","max_new_tokens":64}'
```

응답 필드: `text`, `output_tokens`, `request_id`, `sequence`, `queue_wait_ms`, `processing_ms`.

- 입력: 비어 있지 않은 문자열, 최대32768문자 및 **chat template 포함2048토큰**.
- 출력 상한 `max_new_tokens`: 기본128, 범위1~512. EOS가 나오면 일찍 끝날 수 있다.
- `output_tokens`는 실제 생성 토큰 수(EOS 등 생성된 special token 포함)다.
- BF16, SDPA, greedy, thinking disabled. 원본 Transformers `generate()` 사용.
- 과거 실험의 `min_new_tokens=max_new_tokens=128`과 다르므로 지연시간을 그대로 비교하면 안 된다.

## YOLO 요청

```bash
python3 clients/http/request_yolo.py /path/to/image.jpg
```

```bash
curl -s http://127.0.0.1:8002/detect -F 'file=@/path/to/image.jpg'
```

응답 필드: `width`, `height`, `detections`, 공통 request/sequence/timing 필드.
각 detection은 `class_id`, `label`, `confidence`, `xyxy`를 가진다.
`xyxy`는 **원본 이미지 크기 기준 픽셀 좌표**이며 정규화 좌표가 아니다.

- JPEG/PNG 한 장, 최대10MiB 및 decoded16M pixels. 실제 파일 내용을 검사한다.
- 원격 URL/서버 파일 경로/동영상/결과 이미지 저장은 지원하지 않는다.
- CUDA FP16,640×640,Batch1, 공식 Ultralytics `predict()` 사용.
- 업로드 이미지의 검증·RGB 디코딩은 Queue에 넣기 전 CPU에서 수행한다.

## 시간과 로그

- `queue_wait_ms`: 검증된 입력이 enqueue된 시점부터 consumer가 꺼낼 때까지.
- `processing_ms`: dequeue 후 모델 어댑터 반환까지(스레드 전달·모델별 전처리·추론·결과 준비 포함).
  순수 GPU kernel latency가 아니며 최초 이미지 검증·디코딩과 HTTP 응답 직렬화/전송은 제외한다.
- CLI의 `http_e2e_ms`: HTTP 전송부터 결과 JSON 수신/파싱까지. 로컬 파일 읽기·요청 생성은 제외.
- HTTP E2E에는 입력 업로드/검증,Queue 대기,처리,응답 전송 등이 포함된다.
- 서버는 요청 본문/프롬프트/이미지/생성 텍스트를 로깅하지 않는다. 경로·상태·시각·시간과
  request_id/sequence 기반 inference 시작·종료를 기록한다. Uvicorn 기본 access log는 꺼 뒀다.

```bash
docker logs -f cj-qwen-api
docker logs -f cj-yolo-api
```

## 기본 오류 응답

| 상태 | 의미 |
|---|---|
|400|이미지 형식/파일이 잘못됨|
|413|애플리케이션 이미지 byte/pixel 제한 초과|
|422|누락/잘못된 입력 또는 Qwen 입력 토큰 상한 초과|
|429|해당 모델의 대기 Queue가 꽉 참|
|500|추론 실패(내부 예외 문자열은 클라이언트에 노출하지 않음)|
|503|종료 중 등 요청을 받지 않는 상태|

로그의499는 클라이언트 연결 종료를 관측했다는 의미다. 이미 종료된 클라이언트가
그 응답을 받는다는 뜻은 아니다. 정상적인 중복 요청을 Busy로 거절하지 않는다.
업로드 제한은 파싱 후 애플리케이션 검사이며, production DoS/네트워크 계층의
엄격한 body-size 제한/인증/요청 rate limit을 제공하는 것은 아니다.

## 빌드/실행

Spark 작업 경로: `/home/avees/cj-serving`.
`serving/`, `clients/`, `containers/`, `scripts/`, `.dockerignore`, `requirements-api.txt`를 동기화한다.
모델 부모 이미지와 캐시/YOLO 가중치는 기존 단계에서 준비한 것을 사용한다.

```bash
bash scripts/build_serving.sh
bash scripts/start_serving.sh
```

가중치·입력 asset은 read-only 마운트, runtime cache는 `~/cj-serving/runtime/{qwen,yolo}`다.
시작 스크립트는 기존 동명 컨테이너/사용 중 포트/GPU compute 작업을 발견하면 거부한다.
기존 컨테이너를 자동으로 덮어쓰거나 다른 실험 작업을 종료하지 않는다.
`--reload`나 Uvicorn `--workers 2`를 사용하면 안 된다(중복 모델 로딩/복수 Queue 위험).

모델 로딩은 수분 걸릴 수 있다. 로그의 `Application startup complete` 또는
`curl -fsS http://127.0.0.1:8001/openapi.json` 성공 이후 요청한다.
시작 전 연결 거부/리셋은 모델 추론 지연시간으로 측정하지 않는다.
클라이언트 timeout 기본300초는 `--timeout`으로 변경 가능하다. 큐가 길면 더 필요할 수 있다.

종료/재배포 대상은 API 컨테이너 두 개뿐이다. 기존 `*-dev`와 부모 이미지는 유지한다.
프로세스 종료 시 대기 요청은 영속 저장되지 않는다. 자동 복구/재시작/재시도는 구현하지 않았다.

## 테스트

Python3.12 개발 환경:

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check serving clients tests/test_serving*.py scripts/smoke_serving.py
.venv/bin/python -m compileall -q serving clients
bash -n scripts/build_serving.sh scripts/start_serving.sh
```

GPU 없이 Queue FIFO/직렬화/용량/취소/예외,API 입출력,모델 로딩1회,모델 간 독립성을 검사한다.
실제 TCP를 사용하는 회귀 테스트도 포함한다(단순 ASGI mock으로 대체하지 않음).
Spark 실제 HTTP 시험은 고유 결과 경로로 실행한다:

```bash
python3 scripts/smoke_serving.py --output results/http-smoke-NEW_RUN_ID
```

검증 결과: `results/serving/http-smoke-20261102-verified/summary.json`.
정상 추론8건,독립 Queue/직렬 처리,클라이언트 취소,모델 간 처리 구간 중첩을 검증했다.
성능/SLO/통계적 개선을 입증하는 부하 실험은 아니다.

## 범위 밖

Kubernetes 모델 배포·GPU 공유·외부 Queue/DB·배치·스트리밍·재시작/복구·인증/HTTPS·대시보드.
Kubernetes GPU plugin은 Docker의 GPU 사용을 추적하지 않는다. 향후 K8s로 이전할 때는
현재 API 실행과 이미지 전달/GPU 공유 방식을 명시적으로 정리해야 한다.
독립 코드 리뷰 subagent는 현재 계정의 모델 미지원으로 실행하지 못했다. 직접 코드 검토,
회귀 테스트 및 실제 GPU/HTTP 검증을 수행했으며 production-ready를 주장하지 않는다.
