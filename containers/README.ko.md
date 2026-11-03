# Spark 모델별 컨테이너

## 범위

- `cj-qwen:9b-cu130`: Qwen3.5-9B 텍스트 생성용 개발/실행 이미지
- `cj-yolo:26l-cu130`: YOLO26l 객체 검출용 개발/실행 이미지
- `cj-spark-base:25.09-cu130`: 공통 NVIDIA GPU 기반 이미지

현재는 모델 실행 환경과 검증 도구이며 HTTP 서빙 API/Kubernetes 배포 완료 상태가 아니다.
호스트 OS, 드라이버, 기존 연구 이미지/가중치는 변경하지 않는다. 새 이미지와 실험 파일만 생성한다.

## 기반과 선택 근거

공식 `nvcr.io/nvidia/pytorch:25.09-py3`의 ARM64 이미지:
`sha256:f3b4a33fd60d5e0358287bb44d57e91eda45e8f1681fef1bfd6c969371417130`.
Ubuntu 24.04, CUDA 13.0, NVIDIA PyTorch 2.9.0a0 및 Triton 3.4.0 조합을 사용한다.
Spark는 Jetson/L4T 타깃이 아니므로 Jetson 전용 베이스를 사용하지 않았다.
최신 이미지라는 이유로 호스트 드라이버를 업그레이드하지 않는다.

- [NVIDIA 릴리스 정보](https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/rel-25-09.html)
- [NVIDIA Spark PyTorch 플레이북](https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/playbook-pytorch-fine-tune)

## 모델별 의존성

| 항목 | Qwen | YOLO |
|---|---|---|
| PyTorch/CUDA | NVIDIA 베이스 제공 버전 유지 | 동일 |
| 실행 라이브러리 | Transformers 5.22.1 | ultralytics-opencv-headless 8.4.198 |
| 선형 어텐션 | flash-linear-attention / fla-core 0.4.2 | 해당 없음 |
| convolution | causal-conv1d 1.7.0 공식 CUDA13/torch2.9/CPython3.12/aarch64 ABI TRUE wheel | PyTorch 제공 연산 |
| 정밀도 | BF16 | FP16, 공식 `quantize=16` 인자 |

최신 FLA 0.6.0은 이 베이스 Triton에 없는 Gluon API를 요구해 실제 GPU import가 실패했다.
코드를 수정하지 않고 호환되는 공식 0.4.2 배포를 선택했다.
FLA는 설치 여부뿐 아니라 실제 커널 계산과 Transformers dispatcher 선택을 검증한다.

YOLO Headless 패키지는 원본과 동일한 모델/API를 제공하는 공식 서버용 배포다.
GUI용 OpenCV와 화면 라이브러리를 억지로 추가하거나 런타임 라이브러리를 숨기지 않는다.
[공식 Headless 안내](https://docs.ultralytics.com/quickstart/)

공통 이미지에서 사용하지 않는 학습용 `nvidia-resiliency-ext`와 deprecated `pynvml`을 제거하고,
유지보수되는 `nvidia-ml-py`를 설치했다. 모델 구현 수정/monkeypatch/경고 필터는 사용하지 않았다.
각 최종 이미지에서 `pip check`를 수행한다.

## 빌드

Spark 작업 경로: `/home/avees/cj-containers`.
이 저장소의 `containers/`, `scripts/`, `.dockerignore`를 같은 구조로 복사한 후:

```bash
bash scripts/build_images.sh
```

NVIDIA의 torch/torchvision/Triton을 일반 PyPI wheel로 교체하지 않는다.
모델 가중치와 데이터는 이미지에 포함하지 않고 볼륨으로 제공한다.
최종 이미지 ID와 실제 패키지 버전은 결과 디렉터리에 기록한다.
현재 직접 의존성 및 기반 이미지가 고정돼 있지만 모든 transitive wheel까지 vendoring한
hermetic/offline rebuild를 제공하는 것은 아니다. 해석된 버전 목록은 이미지의
`/opt/requirements-resolved.txt`에 보존된다.

## 실행/개발

Qwen의 기본 모델 경로는 `/cache/models--Qwen--Qwen3.5-9B/snapshots/` 아래
`c202236235762e1c871ad0ccb60c8ee5ba337b9a`다. 다른 경로는 `--model`로 지정한다.
로컬 Hugging Face 캐시는 read-only로 마운트한다.
YOLO 가중치와 공개 테스트 이미지는 `~/cj-containers/assets/`에 준비한다.
초기 탐색에서 사용한 파일 해시와 URL은 이전 results에 남아 있다.

개발용 shell 예시(포트/특권 모드 없음):

```bash
docker run --rm -it --gpus all --shm-size 2g \
  --user "$(id -u):$(id -g)" -e HOME=/runtime \
  -v "$HOME/cj-containers/results/dev-qwen:/runtime" \
  -v "$HOME/.cache/huggingface/hub:/cache:ro" \
  -v "$HOME/cj-containers/scripts:/app/scripts:ro" \
  --entrypoint bash cj-qwen:9b-cu130
```

`dev-qwen` 디렉터리는 먼저 생성한다. YOLO는 이미지명을 `cj-yolo:26l-cu130`로 바꾸고
`-v "$HOME/cj-containers/assets:/assets:ro"`를 추가한다.
직접 구현한 harness는 host에서 수정해 마운트할 수 있지만 검증된 upstream 모델 코드는 수정하지 않는다.
패키지 변경은 Dockerfile로 반영해 이미지를 재빌드한다.

## 가속 커널 검사

```bash
mkdir -p results/kernel-check
docker run --rm --gpus all --network none \
  --user "$(id -u):$(id -g)" -e HOME=/output \
  -e TRITON_CACHE_DIR=/output/triton \
  -v "$PWD/results/kernel-check:/output" \
  --entrypoint python cj-qwen:9b-cu130 /app/scripts/check_gpu_kernels.py
```

검사 자체는 reference 수식과 수치 비교를 하지만 서비스/측정 경로는 reference로 우회하지 않는다.
Qwen Worker는 가속 바인딩이 없으면 실패한다. CUDA profiler trace로 실제 모델 실행도 확인한다.

## 별도 컨테이너 비교 실험

호스트 Python에는 psutil이 필요하다(현재 Spark에 5.9.8 설치됨).

```bash
timeout --signal=TERM --kill-after=40 1800 \
  python3 scripts/run_containers.py --root "$HOME/cj-containers" --seconds 60
```

- 단독 LLM → 단독 CV → 두 컨테이너 상주/LLM만 활성 → CV만 활성 → 동시 활성
- 각 활성 Worker 동시 요청 1개, closed-loop, 각 조건 60초
- 고정 입력/정밀도, 워밍업 및 profiler 수행은 측정에서 제외
- 코드, 이미지 ID, raw request, resource sample, profiler trace, acceleration binding 기록
- GPU compute 작업이 이미 있으면 시작하지 않으며 자기 컨테이너만 종료한다.
- 30분 상한 및 worker-ready/phase 대기 제한이 있으며 SIGTERM 처리 시 자기 컨테이너를 정리한다.

이 실험은 아직 API E2E/SLO/장애 복구/오픈루프 과부하 검증이 아니다.
Kubernetes 배포와 GPU 공유 설정은 추후 별도 구성·검증한다.

## 이름이 고정된 개발 컨테이너

`bash containers/start-dev.sh`는 `cj-qwen-dev`, `cj-yolo-dev`를 만든다.
이 컨테이너는 shell 접근용으로만 대기하며 모델을 상주시키거나 HTTP 서비스를 제공하지 않는다.
GPU 메모리를 계속 점유하지 않도록, 실제 모델 프로세스는 필요할 때 실행한다.
`docker exec -it cj-qwen-dev bash` / `docker exec -it cj-yolo-dev bash`로 접근할 수 있다.
공통 scripts 디렉터리만 편집 가능하게 마운트하고 모델/데이터는 read-only다.
기존 동명 컨테이너는 덮어쓰지 않는다. 외부 포트와 네트워크는 열지 않는다.
