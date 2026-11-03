# 최소 FastAPI 서빙 구현·검증 결과

검증일: 2026-11-02. 현재 API 모델은 Spark Docker 컨테이너에 상주한다.

## 구현 범위

- Qwen POST /generate, YOLO POST /detect, 자동 /docs.
- 모델별 상주 인스턴스1·독립 FIFO1·추론 스레드1. 대기 기본8개, 실행1개.
- 모델 간 상태 확인, 공유 Queue, 공통 GPU Lock 없음. 정상 중복 요청은 대기하고 큐 포화 시에만429.
- 모델 원본 코드/기존 실험 worker/기존 개발 컨테이너·이미지 유지.
- 이번 범위는 Docker HTTP API다. Kubernetes 모델 배포, GPU 공유 설정, SLO/부하/복구 검증은 하지 않았다.

## 실제 HTTP 기능 시험

정상 추론8건 모두 성공. 클라이언트가 포기한 대기 요청1건은 추론하지 않고 건너뛰었고, 잘못된 입력 시험은 예상422를 반환했다.

| 요청 | 생성 토큰 | Queue ms | 처리 ms | HTTP E2E ms |
|---|---:|---:|---:|---:|
| qwen_one | 18 | 0.03 | 1610.24 | 1612.22 |
| qwen_two | 32 | 0.04 | 2847.10 | 2849.29 |
| yolo_one | — | 0.04 | 23.29 | 36.30 |
| yolo_two | — | 0.03 | 11.30 | 16.07 |
| parallel_yolo_one | — | 28.04 | 31.24 | 71.06 |
| parallel_yolo_two | — | 0.05 | 32.27 | 40.14 |
| parallel_qwen_first | 128 | 0.02 | 11419.48 | 11421.62 |
| parallel_qwen_second | 64 | 11102.37 | 5716.49 | 16821.34 |

- Qwen 두 번째 동시 요청은 약11.10초 대기 후 순차 실행됐다.
- 같은 구간 YOLO 요청은 약40~71ms 안에 응답해 Qwen 완료까지 기다리지 않았다.
- 실제 시작/종료 로그로 모델 내 추론 비중첩, 모델 간 처리 구간 중첩, request_id별 응답 연결을 확인했다.
- 두 YOLO 요청의 네트워크 시작 순서와 Queue 순서는 다를 수 있다. FIFO는 입력 검증 후 enqueue 기준이며 sequence로 확인한다.
- 모델별 backend_loaded/model_ready 이벤트는 각1회다. 반복 HTTP 요청이 모델을 다시 로딩하지 않았다.
- 이 수치는 서로 다른 입력/생성 길이를 사용한 단회 기능 시험이다. 과거 고정128토큰 baseline과 비교하거나 SLO/성능 개선 근거로 사용하지 않는다.
- 처리시간은 순수 GPU kernel time이 아니며 이미지 사전 검증/응답 전송 등이 제외된다. 클라이언트 E2E와 구분한다.

## 검증 증거

- `audit.json`, `http-smoke-20261102-verified/summary.json`: 최종 결과.
- `http-smoke-20261102-verified/qwen.log`, `yolo.log`: 요청·Queue·추론 로그.
- `client-qwen-example.json`, `client-yolo-example.json`: 제공한 CLI 클라이언트 실제 실행 결과.
- `integrity-qwen.json`, `integrity-yolo.json`: upstream Python/확장 파일 RECORD 무결성 확인, mismatch0.
- `deployment.json`: 새 API 이미지 ID, 컨테이너 running, OOM 없음, host127.0.0.1 포트만 publish, Uvicorn workers1.
- `versions-qwen.json`, `versions-yolo.json`: 실제 이미지 패키지 버전. 두 이미지 pip check 통과.
- `source/`, `source-sha256.json`: 실제 API 코드 및 실험 도구 스냅샷.
- CPU 단위/계약/TCP 회귀 테스트29개 통과. Ruff lint, compileall, Bash 구문 검사 통과.
- 기존 scripts/worker.py SHA-256이 구현 전 스냅샷과 일치한다.

## 발견·수정한 문제

1. Queue에서 Future에 전달한 예외가 살아 있는 consumer coroutine traceback을 유지하면 unittest의 frame 정리 중 consumer가 종료될 수 있었다. 전파 전 traceback을 분리하고 회귀 테스트로 검증했다.
2. 실제 HTTP에서 BaseHTTPMiddleware 기반 로거를 사용할 때 대기 클라이언트의 연결 종료를 감지하지 못했다. 순수 ASGI 로거로 receive 채널을 그대로 전달해 수정했다. 실제 TCP 회귀 테스트와 Spark 시험에서 취소 항목의 추론 시작이 없음을 확인했다.
3. 초기 테스트 도구의 readiness 대기가 모델 로딩 중 TCP reset을 처리하지 못했다. 일시적 connection error를 기다리도록 도구만 수정했다.
실패 시도 결과는 `http-smoke-20261102/`, `http-smoke-20261102-fixed/`에 남겨 두고 최종 PASS와 구분했다.

## 남은 제한

- 외부 공개용 인증/TLS/DoS 방어, 영속 Queue, 배치, 스트리밍, 모델 장애 복구/자동 재시작 없음.
- 클라이언트 연결 종료가 실행 중 GPU 작업을 강제로 중단하지는 않는다. 대기 중 요청만 실행 전에 건너뛴다.
- 모델 가속 경로는 Qwen 바인딩/YOLO CUDA FP16 시작 검사로 확인했다. API를 대상으로 profiler를 다시 수집한 성능 분석은 이번 범위가 아니다.
- 독립 코드 리뷰 subagent는 계정의 모델 미지원으로 실행하지 못했다. 직접 검토 및 자동/실제 실행 검증을 수행했으며 production-ready를 주장하지 않는다.

사용 방법: [최소 서빙 문서](../../docs/minimal-serving.md).
