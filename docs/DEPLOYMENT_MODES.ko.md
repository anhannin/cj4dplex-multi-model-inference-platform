# 배포 모드와 실제 실행 경계

아래는 존재하는 실행 경로의 설명이지 범용 turnkey launcher가 아니다. GPU·서버·클러스터 변경 없이 소스와 보존 template을 확인했다. 명령을 실행하면 Deployment scale/patch와 MPS 중단이 발생하므로, 여기서는 실행하지 않았다.

## 모드를 혼합하지 않기

| 모드 | GPU 설정 | 입력/큐와 용도 |
|---|---|---|
| 원본 No-MPS baseline | MPS/Green 없는 원본 node. `k8s/serving/` 또는 Docker 경로 | domain42, 기본 queue8. 동결 원본은 `baseline/`의 기록이 기준이다. |
| native595 control | native driver 595.99.02, Green off, MPS daemon 없음, 실제 CUDART13.1 | 최종 Burst의 대조군. 원본 baseline과 드라이버/runtime/계측/부하가 같다는 뜻이 아니다. |
| native595 일반 MPS (`mps-only`) | 일반 daemon `nvidia-cuda-mps-control -d`, 정적 partition 없음, Green off | 최종 Burst 비교군. 각 프로세스 visible SM48이며 전용48SM 보장은 아니다. |
| native595 static | daemon `-d -S`, `sm_partition add`로 고정 8/40 등 생성, 각 client에 partition ID 전달, Green off | 최종 Burst 5개 분할 비교. Q8/Y40은 해당 Burst 결과의 후보이지 영구 운영 배포 권고가 아니다. |
| 복원/관측된 상시 서빙 | 사용자 systemd 일반 MPS + Green Q16/Y32 | domain42, 기본 queue8, forced length 없음. 최종 static8/40 배포와 다르다. |

최종 Burst는 Qwen queue16, YOLO queue512, 요청 DDS depth512, domain74와 `BENCH_FORCE_LENGTH=1`을 쓴다. 일반 node는 queue8, DDS depth32다. 큐 용량과 GPU SM 수의 숫자를 혼동하지 않는다. 근거는 `diagnostics/green_burst/generate.py`, `diagnostics/mps_static/plan.py`, `diagnostics/mps_concurrency/serving.py`다.

## 실제 entrypoint와 파일 배치

### 원본 ROS 경로

`containers/qwen/Dockerfile.ros` / `containers/yolo/Dockerfile.ros`는 각각 부모 `cj-qwen:9b-cu130` / `cj-yolo:26l-cu130`에 ROS를 설치하며 entrypoint는 다음 형태다.

```bash
source /opt/ros/jazzy/setup.bash && exec python /app/ros2/qwen_node.py "$@"
source /opt/ros/jazzy/setup.bash && exec python /app/ros2/yolo_node.py "$@"
```

`k8s/serving/{qwen,yolo}.json`은 `docker.io/library/cj-qwen-ros:9b-timing-v1`, `docker.io/library/cj-yolo-ros:26l-timing-v1`, `imagePullPolicy: Never`를 지정한다. 로컬 이미지 사전 준비가 필요하며 태그만으로 내용 동일성을 보장하지 않는다. `scripts/start_ros2.sh`는 다른 Docker 태그 `9b-eos`/`26l-uuid`를 사용하므로 최종 실험 launcher로 대체하지 않는다.

공통 환경은 `HOME=/runtime`, `PYTHONUNBUFFERED=1`, `OMP_NUM_THREADS=4`, `HF_HUB_OFFLINE=1`, `TRITON_CACHE_DIR=/runtime/triton`, `YOLO_CONFIG_DIR=/runtime/ultralytics`, `ROS_DOMAIN_ID=42`, `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`, `RMW_IMPLEMENTATION=rmw_fastrtps_cpp`, `NVIDIA_DRIVER_CAPABILITIES=compute,utility`다. 기본 manifest 볼륨은 다음과 같다.

| 볼륨 | 실제 경로 |
|---|---|
| writable runtime | `emptyDir` → `/runtime` |
| Qwen cache (RO) | `/home/avees/.cache/huggingface/hub` → `/cache` |
| YOLO assets (RO) | `/home/avees/cj-containers/assets` → `/assets` |

Qwen 기본 모델은 `/cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a`다. nodeSelector `spark-e6d6`, UID/GID/fsGroup1000, `runtimeClassName: nvidia`, hostNetwork/hostIPC는 이 호스트의 전제다. 가중치·이미지·드라이버를 Git만으로 제공하지 않는다.

### 최종 native-static 실험 경로

`diagnostics/mps_static/eval_runner.py`는 `GREEN_BURST_ROOT`를 실행 bundle root로 읽는다. 이름에 GREEN이 남아 있어도 이 조건에서 Green을 사용한다는 뜻은 아니다. 실제 보존 root는 `/home/avees/cj-static-eval/20261110-v1`이다. `src/`, `baseline/`, `backup/`, `workload.json`, verification 사전조건 및 helper alias bundle이 필요하다.

실제 container command는 ROS setup 후 `python /experiment/src/qwen_burst_node.py --ros-args -p queue_capacity:=16` 또는 `yolo_burst_node.py ... queue_capacity:=512`다. 실행 root를 hostPath로 `/experiment`에 연결하고 `PYTHONPATH=/experiment/src`, `PAIR_LABEL`, `EXPECTED_SMS`, `CUDA_HOME=/usr/local/cuda-13.1`을 전달한다. `/usr/local/cuda-13.1`은 동일 경로로 RO mount하고 `LD_LIBRARY_PATH=/usr/local/cuda-13.1/lib64:/usr/local/cuda/lib64:/usr/local/nvidia/lib64`를 설정한다.

MPS 조건만 `CUDA_MPS_PIPE_DIRECTORY=<root>/eval-pipe`와 동일 절대경로 socket mount를 추가한다. static 조건만 `CUDA_MPS_SM_PARTITION=<실제 생성된 opaque GPU/partition ID>`를 추가한다. `sm_partition add <GPU UUID> <SM/2>`는 이 GB10의 2SM chunk 기준이며 다른 GPU의 보편 규칙이 아니다. runner는 실제 SM property, MPS membership, CUDA runtime13010을 검사한다.

**frozen 이미지 Torch build CUDA는13.0, 실제 로드한 CUDART는13.1이다.** 호스트 CUDA13.1 overlay와 native595 환경에서 측정했으며, CUDA13.1이 완결된 새 self-contained 이미지를 빌드/검증한 것이 아니다. 실제 template 근거는 `results/static-eval/20261110-v1/verification/r1-static-q8-y40-warmup-deployment.json`이다.

### 복원된 일반 서빙

`diagnostics/mps_concurrency/serving.py`가 `/experiment/src/{qwen,yolo}_green_node.py` 실행 template을 만든다. MPS socket 존재 및 control 응답 확인 뒤 시작하며 root 기본값은 `/home/avees/cj-serving/mps-green-v1`이다. `cj-cuda-mps.service`는 같은 UID의 사용자 서비스다. CUDA native Green adapter는 환경별 빌드가 필요하다. 호스트 설치 bundle의 `launch_deploy.sh`와 helper PYTHONPATH에 의존하며, 저장소 파일 하나만 실행하는 이식형 설치기가 아니다. 자세한 절차는 [기존 MPS+Green 안내](../k8s/mps-green/README.ko.md)에 보존한다.

## 운영 경계

- `gpu.shared` 슬롯2개는 동일 GPU 접근의 자원표현이다. 50% 성능/메모리 보장이나 SM partition이 아니다. device-plugin MPS sharing 모드로 전환한 것도 아니다.
- hostIPC와 같은 UID, 동일 socket 경로가 연결 전제다. MPS는 메모리·장애·보안의 완전 격리가 아니다.
- startup/readiness는 `/tmp/cj-model-ready` PID marker와 `kill -0` 검사다. 기능적 응답/liveness 보장도, ROS 트래픽 gate도 아니다.
- 복원 시 실행 client를 먼저 내린 후 실험 daemon을 중지하고 원본 template·replica 및 일반 서빙 MPS를 복구한다. runner의 복원은 당시에 검증한 경로이며 현재 서버 상태를 확인했다는 뜻이 아니다.
- Green off에서도 생성기의 transitive Green/Burst helper가 필요하다. `results/<run>/src/` alias 묶음과 원본 generator/runtime을 보존한다.

관련: [구현 범위](IMPLEMENTATION.ko.md), [재현 경계](REPRODUCIBILITY.ko.md), [아키텍처](ARCHITECTURE.ko.md).
