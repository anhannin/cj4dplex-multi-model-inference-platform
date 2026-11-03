# 모델별 단일 파일 FastAPI

## 파일

- `qwen_api.py`: FastAPI + Qwen 로딩 + 전용 FIFO + 추론 스레드 + 원본 generate() + HTTP 응답
- `yolo_api.py`: FastAPI + YOLO 로딩 + 전용 FIFO + 추론 스레드 + 원본 predict() + HTTP 응답

각 파일만으로 자기 모델 서버를 실행한다. 공통 모드 파일, 별도 Backend/모델 호출 래퍼,
`serving/` 또는 다른 프로젝트 모듈 import가 없다. 모델용 라이브러리와 가중치는 별도로 필요하다.
기존 `serving/` 구현은 과거 버전과 회귀 테스트용으로 유지했다.

## 실행 구조

```text
POST /generate -> Qwen 전용 queue.Queue -> Qwen worker thread -> model.generate -> 자기 HTTP 요청에 응답
POST /detect   -> YOLO 전용 queue.Queue -> YOLO worker thread -> model.predict -> 자기 HTTP 요청에 응답
```

- 모델은 worker 시작 시1회 로딩한다. 기본 대기8개 + 실행1개, FIFO.
- 두 서버는 서로의 Queue/모델 상태를 확인하지 않고 독립적으로 실행한다.
- Uvicorn workers1 고정. 다른 프로세스로 복제하면 모델과 Queue도 복제된다.
- HTTP 함수는 enqueue 후 결과 Future를 기다린다. 이벤트 루프에서 GPU 추론하지 않는다.
- Future 결과/예외 설정은 loop.call_soon_threadsafe를 통해 ASGI 스레드에서 수행한다.
- Queue 포화만429. 일반 동시 요청은 기다린다. 대기 중 연결 종료는 실행 전에 건너뛴다.
- 실행 중 GPU 작업은 강제 취소하지 않는다. 재시도/복구/영속 Queue/스트리밍/배치는 없다.

## Spark 상태

|구분|새 이미지|검증용 컨테이너|
|---|---|---|
|Qwen|`cj-qwen-api:9b-single`|`cj-qwen-api-single`|
|YOLO|`cj-yolo-api:26l-single`|`cj-yolo-api-single`|

두 이미지를 빌드하고 실제 HTTP 검증을 마친 뒤 새 컨테이너만 정지했다.
기존 ROS 모델과 개발 컨테이너는 그대로 유지했다. ROS와 API를 모두 켜면 모델이 중복 상주하므로
비교 실험에서는 실행할 버전을 명시적으로 선택해야 한다.
서버 작업 경로: `/home/avees/cj-api-single`.

이미 생성된 검증 컨테이너를 다시 시작하려면:

```bash
docker start cj-qwen-api-single cj-yolo-api-single
```

cold start 후 로그에 Application startup complete가 나와야 HTTP 요청을 받는다.
Qwen은 단순화를 위해 별도 warmup 함수를 두지 않으며 첫 요청에는 kernel JIT/autotuning이 포함될 수 있다.

## 단일 파일 직접 실행

모델 의존성이 준비된 Python3.12 환경에서:

```bash
HOST=127.0.0.1 PORT=8001 python qwen_api.py
HOST=127.0.0.1 PORT=8002 python yolo_api.py
```

기본 가중치 경로는 컨테이너 마운트 `/cache/.../Qwen3.5-9B` snapshot 및 `/assets/yolo26l.pt`다.
다른 경로는 Qwen `MODEL_PATH`, YOLO `YOLO_MODEL_PATH` 환경변수로 지정한다.
공통 `QUEUE_CAPACITY` 기본8. `HOST`/`PORT`는 각 파일에서 읽는다.
가중치는 로컬 파일만 사용하고 모델 소스는 수정하지 않았다.

## 이미지 빌드/새 컨테이너 생성

기존 검증된 NVIDIA 모델 부모 이미지가 필요하다.

```bash
docker build -f containers/qwen/Dockerfile.single-api -t cj-qwen-api:9b-single .
docker build -f containers/yolo/Dockerfile.single-api -t cj-yolo-api:26l-single .
bash scripts/start_singlefile_api.sh
```

시작 스크립트는 기존 동명 컨테이너와 사용 중 포트를 덮어쓰지 않는다.
weights/assets는 read-only, API 포트는 호스트127.0.0.1:8001/8002에만 publish한다.
외부 공개/방화벽 변경/인증/TLS/ROS 연결/Kubernetes 모델 배포는 이번 작업에 포함하지 않는다.
YOLO 선택 codec pi-heif1.4.0을 빌드 때 설치해 미인식 이미지 처리 중 런타임 설치를 피한다.

## 요청

```bash
curl -s http://127.0.0.1:8001/generate -H 'Content-Type: application/json' \
  -d '{"text":"Explain GPU contention briefly.","max_new_tokens":64}'
curl -s http://127.0.0.1:8002/detect -F 'file=@/path/to/image.jpg'
```

자동 문서: `http://127.0.0.1:8001/docs`, `http://127.0.0.1:8002/docs`.
로컬 PC에서 접근할 때는 SSH 터널을 사용한다.
기존 `clients/http/request_qwen.py`, `clients/http/request_yolo.py`도 같은 계약으로 사용할 수 있다.

Qwen: 비어 있지 않은 text, 최대32768문자 및 chat template 포함2048토큰,
max_new_tokens 기본128/범위1~512. 실제 생성 토큰 수와 text를 반환한다.
YOLO: JPEG/PNG 한 장, 최대10MiB/16M decoded pixels. 원본 좌표의 박스·클래스·신뢰도를 반환한다.
공통 응답은 request_id,sequence,queue_wait_ms,processing_ms를 포함한다.

queue_wait_ms는 enqueue 이후 대기, processing_ms는 dequeue 후 입력 변환/추론/결과 준비 시간이다.
이 버전의 이미지 디코딩은 worker 안에서 하므로 기존 버전의 processing_ms와 범위가 다르다.
HTTP 전송/입력 파일 읽기/응답 직렬화 등과도 구분하고, 단순 비교를 성능 개선으로 주장하지 않는다.
기본 오류는400(이미지),413(크기),422(입력),429(포화),500(추론),503(사용 불가)이다.
로그의499는 클라이언트 연결 종료다. 프롬프트/이미지/생성 답변은 서버 로그에 넣지 않는다.

## 검증

- `tests/test_singlefile_api.py`: 파일 독립성·원본 SDK 직접 호출·모델 로딩1회·입출력·FIFO·포화·독립성·실제 TCP 취소 회귀 테스트.
- 기존 테스트34개 + 신규5개를 실행한다. 신규 CPU 테스트는 SDK mock을 사용하며 실제 GPU 검증과 구분한다.
- Spark 실제 GPU HTTP 정상 요청8건 PASS. 순차 처리, 대기 요청 취소, 두 모델 처리 구간 중첩을 확인했다.
- `results/singlefile-api/http-functional/summary.json`과 로그에 원시 결과를 보존했다.
- pip check/Ruff/Python compile/Bash 구문/컨테이너 소스 SHA-256 확인.
- 장기 안정성/복구/부하/SLO/보안 또는 독립 전문 코드 리뷰를 완료했다고 주장하지 않는다.

검토용 ZIP: `downloads/fastapi_single_files.zip`.
