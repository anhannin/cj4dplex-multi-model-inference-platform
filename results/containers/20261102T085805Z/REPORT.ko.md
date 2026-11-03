# Spark 모델별 가속 컨테이너 구축 및 검증

검증일: 2026-11-02 KST. 최종 실행: `20261102T085805Z`.

## 결과 요약

- 공식 NVIDIA ARM64 기반의 Qwen/YOLO 이미지를 각각 구축했다. 실행 의존성 검사와 실제 GPU 추론을 통과했다.
- Transformers의 네 핵심 가속 함수가 causal-conv1d/FLA에 연결됨을 검사하고, 실제 generate의 CUDA profiler에서 해당 커널과 PyTorch Flash Attention 실행을 확인했다.
- YOLO 실제 AutoBackend의 CUDA FP16 파라미터를 검사했다. 원본 모델이 CPU에 남는 정상적인 라이브러리 동작과 실행 백엔드를 구분했다.
- 최종 5개 조건에서 원시 요청 16,065개 중 실패 0. OOM/런타임 traceback/reference fallback 경고 없음.
- 설치된 upstream Python/확장 파일 3,397개를 배포 패키지 RECORD 해시와 대조해 모두 일치했다. monkeypatch나 모델 소스 수정 없음.

## 환경

- 호스트: DGX Spark GB10, aarch64, Ubuntu 24.04.4, Driver 580.173.02. 호스트 OS/드라이버/연구 환경은 변경하지 않았다.
- 공식 base: `nvcr.io/nvidia/pytorch:25.09-py3@sha256:f3b4a33fd60d5e0358287bb44d57e91eda45e8f1681fef1bfd6c969371417130`.
- 컨테이너: Ubuntu 24.04.3, CUDA 13.0, NVIDIA PyTorch 2.9.0a0, Triton 3.4.0. Jetson용 L4T 이미지가 아니다.
- Qwen: Transformers 5.22.1, flash-linear-attention/fla-core 0.4.2, causal-conv1d 1.7.0 공식 aarch64/CPython3.12/cu13/torch2.9/ABI TRUE wheel.
- YOLO: 공식 서버용 ultralytics-opencv-headless 8.4.198, native CUDA FP16.
- 전체 패키지 목록: `../requirements-qwen.txt`, `../requirements-yolo.txt`. 이미지 ID: `../images-final.txt`.

## 실행 조건

- Qwen3.5-9B revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, 텍스트 입력만 사용, BF16, SDPA, 입력 473토큰, 정확히 128토큰 greedy 생성.
- YOLO26l, 640×640, Batch 1, 공식 데모 이미지 2장 교대. 이미지 디코딩은 제외하고 전·후처리 및 CPU 결과 회수 포함.
- 각 모델은 서로 다른 Docker 컨테이너와 프로세스로 실행했다. GPU 분할/MPS/Green Context 미적용.
- 활성 Worker당 closed-loop 동시 요청 1개. 각 조건 60초. 워밍업 3회 및 profiler/JIT autotuning은 정상 상태 측정에서 제외했다.
- 아래 지연시간은 동기화된 모델 호출 wall time이다. HTTP/API/Queue 지연시간이 아니며 LLM 토큰화·출력 디코딩은 제외한다.
- 공통 측정 구간 안에 완전히 포함된 요청만 통계에 사용했다. 경계 요청은 raw JSONL에 보존한다.

## 측정 결과

| 조건 | 모델 | 측정 n | 평균 ms | p95 ms | 구간 내 req/s |
|---|---|---:|---:|---:|---:|
| llm-alone | llm | 5 | 11623.81 | 11670.18 | 0.0833 |
| cv-alone | cv | 6890 | 8.52 | 9.25 | 114.8333 |
| llm-cv-idle | llm | 5 | 11607.98 | 11627.40 | 0.0833 |
| cv-llm-idle | cv | 7040 | 8.37 | 9.06 | 117.3333 |
| concurrent | llm | 3 | 18711.12 | 18735.98 | 0.0500 |
| concurrent | cv | 2116 | 28.15 | 29.44 | 35.2667 |

| 조건 | LLM 평균 TTFT ms | LLM 평균 TPOT ms/token |
|---|---:|---:|
| llm-alone | 181.89 | 90.09 |
| llm-cv-idle | 181.82 | 89.97 |
| concurrent | 297.07 | 144.98 |

## 해석과 한계

- llm: 동시 실행 평균 지연시간은 단독 대비 1.61배(+61.0%).
- cv: 동시 실행 평균 지연시간은 단독 대비 3.30배(+230.3%).
- 다른 모델의 단순 상주보다 동시 추론 시 성능 저하가 크다. 아직 SM/메모리 대역폭/스케줄링 중 어느 것이 주된 원인인지 입증하지 않았다.
- 이전 reference 환경의 단독 LLM 평균 12.08초 대비 현재 11.62초로 전체 시간 변화는 소폭이다. 가속 커널 설치가 큰 전체 지연시간 개선을 보장하지 않으며, 이전/현재 환경 비교는 여러 의존성이 변경돼 순수한 단일 변수 실험이 아니다.
- LLM 표본은 조건별 3~5개다. p95는 계산값일 뿐 tail/SLO 판단이나 통계적 유의성을 주장할 수 없다. 처리량은 60초 경계 요청 제외의 영향을 크게 받는다.
- 두 모델 상주 측정 구간에서 host available memory 최저 약 91.38GiB. 이는 discrete VRAM 측정값이 아니다. Torch allocation/RSS/host RAM을 합산하지 않는다.
- 모델 로딩은 약 151초였다. profiler/JIT autotuning을 포함한 예열 시간은 정상 상태 지연시간과 구분해야 한다. 실제 배포 cold-start/readiness는 추가 측정 대상이다.
- 순서 고정 단회 실험, synthetic text 1종/이미지 2장이다. 정확도/다양한 입력/다중 클라이언트/open-loop Traffic/Queue/장애 복구/SLO 검증은 미수행이다.
- CUDA trace에는 최초 JIT/autotuning 이벤트도 포함된다. trace 내 커널 횟수를 정상 상태 요청당 커널 수로 해석하면 안 된다.

## 구축 중 발견한 문제와 처리

1. FLA 0.6.0이 기본 Triton에 없는 Gluon API를 요구했다. 소스 패치 없이 0.4.2 공식 배포로 고정하고 numerical/GPU/model 검증을 통과했다.
2. GUI용 OpenCV가 libxcb를 요구했다. 공식적으로 동일 모델/API를 제공하는 Ultralytics Headless 배포를 사용했다.
3. NVIDIA 베이스의 unused training resiliency 패키지가 deprecated pynvml을 요구했다. 해당 미사용 패키지와 deprecated provider를 제거하고 유지보수되는 nvidia-ml-py를 설치했다. 두 이미지의 pip check 통과.
4. 최초 통합 검증 도구가 YOLO 원본 CPU 모델을 검사해 실패했다. 실제 CUDA AutoBackend 복사본을 검사하도록 우리 도구만 수정하고 회귀 테스트 3개를 추가했다. 실패 실행 `../20261102T085136Z/`와 시도 로그를 보존했다.

## 검증 증거

- `audit.json`: raw 요청 재검산, 시간/출력 검사, 요약 통계 재계산, 실행 소스 해시 일치.
- `gpu-kernel-proof.json`, Worker별 `*-gpu-events.json.gz`, `*-trace.json.gz`: 실제 모델 GPU 커널 실행 증거. 원본 trace도 서버에 보존된다.
- `../kernel-check/kernel-validation.json`: FP32/BF16 convolution 및 FLA 수치 비교 PASS. BF16 conv 최대 절대 오차 0.00390625, FLA 최대 절대 오차 0.00048828125.
- `../integrity-qwen.json`, `../integrity-yolo.json`: upstream 파일 RECORD 무결성 PASS.
- `../pip-check-qwen.txt`, `../pip-check-yolo.txt`: No broken requirements found.
- CPU 단위 테스트 10개, Python compileall, Bash 구문 검사 통과. 별도 lint/typecheck/CVE 스캔은 미수행.

## 최종 상태와 실행 방법

- Spark 이미지: `cj-qwen:9b-cu130`, `cj-yolo:26l-cu130`.
- 개발 컨테이너: `cj-qwen-dev`, `cj-yolo-dev`. shell 대기 상태이며 모델은 상주시키지 않았다. 포트/네트워크는 열지 않았다.
- `docker exec -it cj-qwen-dev bash` / `docker exec -it cj-yolo-dev bash`로 접근 가능.
- 서버 작업 경로: `/home/avees/cj-containers`. [빌드·실행 문서](../../../containers/README.ko.md).
- 현재 완료 범위는 모델 실행 환경이다. HTTP API와 Kubernetes 배포 및 GPU 공유 설정은 아직 구현하지 않았다.
- 호스트 드라이버/OS/기존 연구 이미지 및 모델 가중치 미변경. 새 이미지·개발 컨테이너·작업 디렉터리만 추가했다.
- Codex가 Dockerfile, 계측/검증 코드와 문서를 작성했다. 실험 결과는 실제 실행 로그에서 산출했다.

## 공식 참고

- [NVIDIA PyTorch 25.09](https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-25-09.html)
- [FLA upstream](https://github.com/fla-org/flash-linear-attention)
- [causal-conv1d 공식 release](https://github.com/Dao-AILab/causal-conv1d/releases/tag/v1.7.0)
- [Ultralytics Headless 설치](https://docs.ultralytics.com/quickstart/)
- [Qwen 모델 카드](https://huggingface.co/Qwen/Qwen3.5-9B)
