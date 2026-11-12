# CJ 4DPLEX Multi-Model AI 추론 운영 인프라

**Qwen3.5-9B + YOLO26l / 단일 DGX Spark / Kubernetes·ROS2 / 지표 기반 GPU 자원 정책 비교**

> **브랜치 구분:** 사용자 요청에 따라 `baseline` 브랜치에도 최신 작업을 반영한다. 최적화 전 동결 원본은 `baseline-frozen-20261103` 태그와 아래 고정 commit으로 보존하며, 성능 비교의 Baseline과 최신 브랜치 이름을 혼동하지 않는다.

서로 다른 두 모델을 독립 Queue/Worker로 서비스하고, 요청 경합을 재현한 뒤 NVIDIA MPS 정적 SM 분할의 효과·비용과 Kubernetes 기본 장애 복구를 검증한 사전과제다. 모델 학습·정확도 향상이 아니라 **문제 재현→측정→가설→검증→기술적 결론**에 집중한다.

## 제출물 바로 보기

| 제출 항목 | 문서 |
|---|---|
| 핵심 요약(1~2페이지) | [Executive Summary](docs/EXECUTIVE_SUMMARY.ko.md) · [2페이지 PDF](docs/EXECUTIVE_SUMMARY.ko.pdf) |
| 기술 보고서 | [문제·실험·분석·최적화·장애·한계](docs/TECHNICAL_REPORT.ko.md) |
| 시스템 구성도 | [설계 설명·Mermaid](docs/ARCHITECTURE.ko.md) · [SVG](docs/architecture.svg) |
| 설치·실행·테스트·재현 | [Reproducibility](docs/REPRODUCIBILITY.ko.md) |
| 소스코드 안내 | [Code Map](docs/CODE_MAP.ko.md) |
| 모델·OSS·AI 보조·구현 범위 | [사용 내역과 라이선스](docs/USAGE_AND_LICENSES.ko.md) |
| 제출 전 상태·남은 결정 | [체크리스트](docs/SUBMISSION_CHECKLIST.ko.md) |
| 정리·검증 기록 | [Cleanup Report](docs/CLEANUP_REPORT.ko.md) |
| 수치 원본 연결 | [자동 생성 결과표](docs/submission/RESULT_TABLES.ko.md) · [원본 SHA와 metrics](docs/submission/metrics.json) |

## 핵심 결과

**주 시나리오: Qwen10건·YOLO300건 동시 Burst.** 같은 native595/CUDART13.1 환경에서 MPS없음을 기준으로 비교했다.

| 지표 | 최적화 없음 | 정적 Qwen8/YOLO40 SM | 변화 |
|---|---:|---:|---:|
| YOLO300건 완료 평균 |16.322초|11.592초|**28.98% 단축**|
| YOLO 요청 E2E p95 |14.963초|10.674초|**28.66% 감소**|
| Qwen 요청 E2E p95 |113.299초|111.876초|약1.26% 감소|

- 7조건×5회. 본측정10,850응답, 워밍업 포함12,005응답 검증. Burst p95는 조건별 pooled 기술통계다.
- **지속 부하 추가40회:** 15req/s에서8/40의 Qwen p95 **9.66%**, YOLO **39.61%** 감소. 8req/s에서는YOLO16.25% 감소로20% 목표에 **미달**했다. 지속 부하 주지표는 실행별p95의5회 평균으로 Burst와 합치지 않는다.
- **Trade-off:** 15req/s의 Qwen 내부TTFT209→487ms 악화. YOLO GPU forward Event도11.31→16.84ms로 증가했으므로 E2E개선을 순수GPU연산단축으로 과장하지 않는다.
- **장애:** GPU유휴 YOLO프로세스 SIGKILL3회, Kubernetes기본재시작 후 첫정상응답4.163~4.504초. 자체복구최적화·무중단·진행중요청보존을 구현한 성과가 아니다.

[SLO 선정 시점·통계와 한계](docs/TECHNICAL_REPORT.ko.md). Burst 탐색 후 목표를 합의했으며 사전등록 holdout 검증이라고 하지 않는다. 모든 부하에서SLO를 충족했다는 주장도 하지 않는다.

## 구현 구조

```text
Qwen client → /qwen/request → 전용 FIFO → Qwen Worker → /qwen/result/r_UUID
YOLO client → /yolo/request → 전용 FIFO → YOLO Worker → /yolo/result/r_UUID
                                        ↓
                              동일 GB10 GPU 공유
```

- 모델마다 별도 Pod/프로세스/큐. 모델이 서로의 진행상태를 참조하지 않으며 텐서 batching은 하지 않는다.
- 원본 Transformers `generate()` / Ultralytics `predict()` 호출을 유지했다.
- `nvidia.com/gpu.shared`는 접근 슬롯이며 SM분할 자체가 아니다. 최종 비교의 정적 SM분배는 MPS가 담당한다.
- 최종 성능 비교에는 **Green Context 미사용**. 과거 탐색 자료는 별도 보존했다.
- UUID는 결과 혼선 방지이지 보안 인증이 아니다. 신뢰된 localhost ROS2 환경이다.

## 재현 시작점

### CPU 테스트·제출 점검

Python3.12와 기존 의존성이 있는 환경에서:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/check_submission.py
```

실제 GPU·ROS 배포 없이 CPU에서 실행하는 회귀/분석검사다. 외부 패키지 취득·완전한 offline build까지 보장하는 것은 아니다. 보존 데이터를 다시 집계하는 검증 명령과 host-specific GPU 실험 준비는 [재현 안내](docs/REPRODUCIBILITY.ko.md)를 따른다.

### ROS 요청 예시 — 준비된 Spark 호스트

```bash
source ~/.config/cj-ros2/spark-jazzy.bash
python3 clients/request_qwen.py --text "GPU 자원 경합을 설명해 줘." --max-new-tokens 128
python3 clients/request_yolo.py --image /path/to/permitted-input.jpg --output /tmp/detected.png
```

위 예시는 이미 준비된 서버를 사용한다. 모델 가중치·입력 이미지는 권한을 확인해 별도 준비한다. 새 서버의 모델 이미지·ROS2·Kubernetes·hostPath·MPS준비를 자동 생략하는 명령이 아니다.

## 환경과 상태를 구분하기

| 구분 | 의미 |
|---|---|
| 동결 baseline | Git ref `6a99fdaf26307e2f0b41f708478fdec3fcfad7ac`; 이전 driver580 기준선·코드·이미지 식별자 보존 |
| 최종 비교 | driver595.99.02, Toolkit13.1.2, 실제CUDART13.1; 동결 이미지의 Torch buildCUDA13.0은 유지하고 host runtime overlay 사용 |
| 마지막 검증된 복원 상태 | 일반MPS+Green Qwen16/YOLO32, 두Pod Ready·실제응답 확인. **추천8/40의 상시배포와 다름** |

현재 체크아웃은 제출용 문서가 추가되고 불필요한 HTTP·개발·일회성 실행기가 제거된 작업트리다. 'baseline branch'라는 옛 README표기는 [원문](docs/history/baseline-root-README.md)에 보관했다. `baseline/FILES.sha256`를 현재작업트리에 그대로 적용하면 갱신된README·빌드/개발 설정과 승인된 삭제 파일이 불일치한다. `scripts/check_submission.py --baseline-only`는 **동결 Git객체677개**를 검증한다. Git없는 제출payload는 `scripts/verify_export.py .`로 포함파일manifest를 검사한다.

## 코드와 결과 위치

| 경로 | 책임 |
|---|---|
| `ros2/`, `clients/` | 선택한 독립 ROS2 노드와 UUID 요청 클라이언트 |
| `containers/`, `k8s/` | 모델 이미지·기본 배포·실험/복원 관련 설정 |
| `diagnostics/mps_static/` | 최종 native MPS 정적 분할·진단·분석 |
| `diagnostics/sustained/`, `diagnostics/fault_idle/` | 지속 부하와 제어된 장애 실험 |
| `tests/`, `scripts/` | 회귀·계측·제출 검증·아카이브 도구 |
| `results/static-eval/`, `results/sustained/`, `results/fault-idle/` | 주요 실측·원시 JSONL·감사·그래프 |
| `optimization/`, 기타 diagnostics | baseline→최적화 과정 재현 및 공통 helper; 최종 경로와 혼합 금지 |
| `baseline/` | 동결 내역·원본 식별자·초기 이미지 복원 안내 |

**하위 과거 문서의 '현재'는 작성 당시의 상태다. 최신 제출 설명은 이 README와 연결된 최종 보고서를 우선한다.** 탐색 코드를 삭제·통합해 당시 측정 소스가 사라지지 않도록 보존했다.

## 제출용 파일 묶음

대형 Nsight/SQLite 원본·모델·개별 샘플사진은 무분별하게 Git에 추가하지 않는다. 원본은 삭제하지 않고 제출용 source/docs/수치/로그를 별도 디렉터리에 복사할 수 있다.

```bash
python3 scripts/export_submission.py --output /absolute/path/outside-this-repo/cj-submission
python3 /absolute/path/outside-this-repo/cj-submission/scripts/verify_export.py \
  /absolute/path/outside-this-repo/cj-submission
```

이 명령은 ignored파일/credentials/가중치·사진·compiled binary·대형profiler자료를 제외하며 **untracked 소스도 포함**한다. 실제 제외경로·SHA는출력`SUBMISSION_MANIFEST.json`에기록한다. 기존run전체raw SHA가모두이묶음에포함됐다는뜻은아니다. GitHub/DockerHub에업로드하거나공개범위를바꾸지않는다.

사용권한·샘플사진권리·AGPL/Enterprise·NVIDIA이미지조건·GitHub/이미지수신자접근확인은[체크리스트](docs/SUBMISSION_CHECKLIST.ko.md)의별도결정항목이다. AI보조작성범위도공개했다. 생산서비스완성도나라이선스검토완료를과장하지않는다.

## 활성 실행파일 정리 (2026-11-12)

선택하지 않은 HTTP스택, 초기preflight·sleep개발컨테이너, 종료대기/수집wrapper를 제거했다. ROS2·baseline·최적화본체·필수Green/MPS helper는 유지했다. [삭제목록·SHA](docs/submission/cleanup-removals.json), [직접 재현명령](docs/REPRO_COMMANDS.ko.md), [실행파일 정리기록](docs/EXECUTABLE_CLEANUP.ko.md). 동결baseline과results의당시실행source사본은의도적으로보존한다.
