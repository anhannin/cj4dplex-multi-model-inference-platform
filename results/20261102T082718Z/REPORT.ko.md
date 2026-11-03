# DGX Spark 1차 탐색 실험 — 2026-11-02

## 결론

Qwen3.5-9B와 YOLO26l은 단독 및 동시 실행에 성공했다. 이 실행에서 실패 요청과 OOM은 없었다. 다른 모델의 메모리 상주만으로는 큰 변화가 관찰되지 않았지만, 동시 추론에서는 두 모델 모두 지연시간이 증가했다. 단, LLM은 최적화 커널이 없는 reference PyTorch 경로이므로 이 결과를 최종 서빙 Baseline이나 SM 경합의 증거로 사용하지 않는다.

## 환경과 조건

- Ubuntu 24.04.4, GB10 (compute capability 12.1), Driver 580.173.02, PyTorch 2.9.0a0 NVIDIA 25.09, CUDA runtime 13.0.
- 프로젝트 전용 venv: Transformers 5.22.1, Ultralytics 8.4.198. 기존 환경/모델 캐시 미수정.
- Qwen revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`: BF16, SDPA, 473 입력 토큰, greedy, 정확히 128 출력 토큰. 이미지 입력은 사용하지 않았다.
- YOLO26l: FP16 설정, 640×640, Batch 1, 공식 데모 이미지 2장 교대. 이미지 파일 디코딩 제외, 전·후처리 및 CPU 결과 회수 포함.
- 독립 프로세스, 각 활성 Worker에 closed-loop 동시 요청 1개. 각 조건 60초, 워밍업 3회. MPS 및 GPU 분할 미적용.
- 각 공통 측정 구간 안에 완전히 포함된 요청만 요약 통계에 사용. 경계 요청은 원시 로그에 보존.
- HTTP/API/Queue 미구현. 아래 수치는 모델 호출 지연시간이며 서비스 E2E가 아니다.

## 결과

| 조건 | 모델 | 측정 n | 평균 ms | p95 ms | 구간 내 완료 req/s |
|---|---|---:|---:|---:|---:|
| llm-alone | llm | 4 | 12077.68 | 12087.71 | 0.0667 |
| cv-alone | cv | 7119 | 8.28 | 8.89 | 118.6500 |
| llm-cv-idle | llm | 5 | 11991.44 | 12018.00 | 0.0833 |
| cv-llm-idle | cv | 7127 | 8.28 | 8.90 | 118.7833 |
| concurrent | llm | 3 | 19345.35 | 19357.96 | 0.0500 |
| concurrent | cv | 2112 | 28.23 | 29.53 | 35.2000 |

LLM 통계 표본은 조건별 3~5개에 불과하다. p95는 계산값일 뿐 tail latency나 SLO 판단에 충분한 근거가 아니다. LLM 구간별 처리량은 60초 경계 제외의 영향을 크게 받으므로 토큰 생성 속도와 함께 해석해야 한다.

| 조건 | TTFT 평균 ms | TPOT 평균 ms/token |
|---|---:|---:|
| llm-alone | 250.78 | 93.12 |
| llm-cv-idle | 255.90 | 92.40 |
| concurrent | 406.90 | 149.11 |

## 해석과 한계

- llm: 동시 실행 평균 지연시간은 단독 대비 1.60배(+60.2%).
- cv: 동시 실행 평균 지연시간은 단독 대비 3.41배(+240.9%).
- GPU utilization 한 가지로 SM, 대역폭, 커널 스케줄링 중 어느 것이 원인인지 판별할 수 없다. 프로파일링과 추가 대조 실험이 필요하다.
- LLM 로그에서 `causal_conv1d` 및 `flash-linear-attention` 부재에 따른 reference fallback을 확인했다. 정확한 추론 경로이지만 느리며, 최적화 커널 또는 지원되는 서빙 백엔드를 먼저 검증해야 한다.
- CV는 deprecated `half` 인자 경고를 매 호출마다 기록했다. 모든 조건에 동일하게 적용됐지만 측정 오버헤드이며, 다음 버전에서는 공식 `quantize=16` 인자로 대체 후 재측정해야 한다.
- 두 모델이 상주한 측정 구간의 host available memory 최저치는 약 93GiB였다. Torch allocator는 LLM 워밍업 후 약 18.84GB, CV 약 0.084GB allocated를 보고했다. 이는 별도 VRAM 측정값이 아니며 RSS/host RAM과 합산하면 안 된다.
- 순서를 고정한 단회 실험이다. 온도·클럭·순서 효과, 모델/입력 다양성, 동시 요청 수 증가, open-loop arrival traffic, Queue 안정성을 검증하지 않았다.
- 단독 모델 로딩 약 151초. 로딩/첫 호출과 정상 상태 추론은 분리했으며, 최종 장애 복구 설계 시 cold start 비용을 따로 확인해야 한다.
- 정확도 평가는 수행하지 않았다. 텍스트 생성과 비어 있지 않은 객체 검출 결과를 sanity check했을 뿐이다.

## 다음 단계

1. 지원되는 빠른 Qwen 커널/백엔드와 최신 CV 정밀도 인자를 검증하고 모델 설정을 고정한다.
2. 반복 측정과 순서 교차 실험으로 정식 단독·동시 Baseline을 확보한다.
3. API/Queue 지연시간을 계측하고 요청 도착률을 단계적으로 높여 SLO와 병목을 정한다.
4. 병목 근거가 확보된 뒤 MPS/Green Context 등 최적화 후보를 선택한다.

## 검증과 산출물

- `summary.json`, Worker별 `*.jsonl`, `*-ready.json`, `*.log`, 조건별 resource JSON 보존.
- 원시 요청 16,376개 검사: 실패 0, LLM 출력 128토큰, CV 검출 결과 존재, 요약 통계 재계산 일치, 실행 소스 SHA-256 일치. `audit.json` 참조.
- 단위 테스트 3개, Python compileall, Bash 구문 검사 통과. 별도 lint/typecheck 도구는 현재 로컬에 설치돼 있지 않아 실행하지 않았다.
- 실행 컨테이너 및 모델 Worker 종료 확인. 종료 후 host available memory 약 114GiB, GPU compute process 없음.
- 원본 실행 소스: `../source-20261102-initial/`. 환경·패키지 버전·이미지 ID·입력 해시는 상위 results 파일 참조.
- 기존 로컬 연구용 이미지에 의존한다. 공개 이미지 기반 재현 환경은 아직 구성하지 않았다.

공식 참고: [Qwen 모델 카드](https://huggingface.co/Qwen/Qwen3.5-9B), [YOLO predict 인자](https://docs.ultralytics.com/modes/predict/).
