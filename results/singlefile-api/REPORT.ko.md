# FastAPI 모델별 단일 파일 검증

최신 사용자 지시: 1번만 진행. 로컬 ROS 연결 작업은 중단했다.

- 배포 코드는 api/qwen_api.py, api/yolo_api.py 두 개다.
- 각 파일에 시작/모델 로딩/독립 FIFO/단일 추론 스레드/HTTP 응답/실행 main이 있다.
- 기존 serving/Backend/공통 mode 모듈에 의존하지 않고 원본 generate()/predict()를 직접 호출한다.
- 새 API 이미지/컨테이너를 기존 것과 구분해 빌드·시험하고, 시험 후 새 API만 중지했다.
- 기존 Spark ROS 노드·개발 컨테이너·OS·드라이버·통신 설정은 변경하지 않았다.

## 검증

- 기존34개 + 신규5개 = CPU 테스트39개 통과.
- 신규 테스트는 SDK mock을 이용해 입력·로딩1회·FIFO·포화429·모델 독립성과 실제 TCP 대기 취소를 검증한다.
- 별도의 Spark 실제 GPU HTTP 정상 요청8건 PASS. 실제 생성 텍스트·검출 결과·토큰 상한·박스 좌표·요청 연결을 검사했다.
- 대기 중 연결 종료 요청은 처리하지 않고 건너뛰었다. Qwen 처리 중 YOLO가 응답했다.
- CPU mock 결과와 실제 GPU 결과를 구분해 보존한다.
- 소스 다운로드 SHA-256 일치, pip check, Ruff, compileall, Bash 구문 검사 통과.

| 요청 | Queue ms | 처리 ms | HTTP E2E ms |
|---|---:|---:|---:|
| qwen_one | 0.07 | 32937.92 | 32940.71 |
| qwen_two | 0.14 | 2830.27 | 2832.53 |
| yolo_one | 0.09 | 40.85 | 44.05 |
| yolo_two | 0.08 | 13.39 | 16.21 |
| parallel_yolo_one | 31.54 | 32.81 | 69.06 |
| parallel_yolo_two | 0.18 | 32.56 | 36.57 |
| parallel_qwen_first | 0.15 | 11333.52 | 11337.31 |
| parallel_qwen_second | 11012.04 | 5666.95 | 16681.92 |

첫 Qwen 요청에는 kernel JIT/autotuning이 포함된다. ROS 모델도 기존 상태로 상주한 동안 수행한 기능 시험이므로, 성능 개선/SLO/독립 자원 격리의 증거가 아니다.
이 구현은 이미지 디코딩을 worker에서 수행하므로 이전 API의 processing_ms와 측정 범위가 다르다.

## 산출물

- http-functional/summary.json, qwen.log, yolo.log: 실제 요청 결과와 처리 구간.
- deployed-code/: 실행 이미지에서 다시 내려받은 소스.
- source-sha256.json, downloads/fastapi_single_files.zip: 검토 소스와 해시.
- all-unit-tests.log, lint.txt, pip-check-*.txt, deployment.txt, containers-final.txt: 검증 기록.
- 사용 방법: [api/README.md](../../api/README.md).

2번 중단 시점에는 Pixi/RoboStack의 독립 패키지 설치가 이미 완료돼 있었다. 이후 활성화·셸 프로파일·네트워크/방화벽 변경·ROS 통신 검증을 진행하지 않았다. 설치 환경은 삭제하지 않았다.
