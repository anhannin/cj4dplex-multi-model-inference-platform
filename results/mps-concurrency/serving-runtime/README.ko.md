# Spark: 두 Pod의 GPU 병렬 실행

기존 Qwen/YOLO Deployment 및 독립 FIFO/ROS 토픽 구조는 유지한다. 같은 UID1000의 호스트 MPS 서버에 두 Pod가 같은 Unix socket 경로로 연결된다. 모델 이미지는 기존 frozen 이미지 그대로이며 프레임워크/모델 소스를 패치하지 않는다.

- 호스트 runtime: `/home/avees/cj-serving/mps-green-v1`
- MPS: 사용자 systemd `cj-cuda-mps.service`, 현재 사용자 linger 설정 사용.
- Green 설정: Qwen16 / YOLO32, 기존 `GreenPair` 및 각자 non-blocking stream.
- 일반 서빙: domain42, 기본 queue8 유지, Qwen 기본 max_new_tokens0(EOS), 요청별 UUID result 채널 유지.
- `BENCH_FORCE_LENGTH`, profiler, 실험용 queue16/512는 일반 서빙에 없음.
- MPS active-thread-percentage는 설정하지 않음. Green과 다른 cap을 중첩하지 않음.
- Kubernetes device-plugin의 `gpu.shared`2개 설정은 파드의 GPU 접근 허용/자원 계산용으로 그대로 유지. 실제 CUDA 프로세스 간 동시 실행은 이번 MPS 연결이 담당한다. Device Plugin의 MPS sharing 모드로 전환한 것이 아니다.

## 상태 확인
```bash
systemctl --user status cj-cuda-mps.service
export CUDA_MPS_PIPE_DIRECTORY=$HOME/cj-serving/mps-green-v1/mps-pipe
echo get_server_list | nvidia-cuda-mps-control
# 위 서버 PID 사용:
echo 'get_client_list <server-pid>' | nvidia-cuda-mps-control
kubectl -n cj-inference get pods
```

모델 시작 명령은 MPS socket 및 제어 명령 응답을 확인한 뒤 실행한다. 시작 시점의 연결 확인이며, 지속적인 장애 탐지/복구 구현은 이번 변경 범위가 아니다. MPS가 실행 중에 중단되면 두 파드를 안전하게 중지/재시작하고 재연결 여부를 확인해야 한다. 이 서비스는 보안 격리나 전용 GPU 메모리 격리를 제공하지 않는다.

## 재생성
리포지터리 루트에서:
```bash
PYTHONPATH=. .venv/bin/python -m diagnostics.mps_concurrency.serving \
  --output results/mps-concurrency/serving-generated
```
`serving.py`는 기존 `ros2/*_node.py`를 기존 Green wrapper 생성기로 감싸고, 기존 추론 호출/queue/토픽을 유지한다. CUDA native adapter는 `diagnostics/green_context/green_bridge.cu` 및 `build.sh`를 사용하며 이번 Spark의 기존 CUDA13/ARM64 빌드 결과를 runtime src에 복사했다. 다른 환경에는 해당 환경에서 다시 빌드해야 한다.

배포 실행기는 `diagnostics/mps_concurrency/deploy.py`다. Spark에서 기존 burst runner helper를 PYTHONPATH에 두고 `GREEN_BURST_ROOT`를 runtime 경로로 지정해 실행한다. 진단 PASS/복원 PASS 및 보수적 공통 시계 겹침 >50ms를 확인한 뒤에만 배포하며, 적용 실패 시 원래 template을 복원한다. 최초 설치용이며 기존 사용자 unit을 임의로 덮어쓰지 않는다.

## 원상 복구
runtime `backup/{qwen,yolo}.json`은 변경 전 실제 Deployment 전체다. 복원 시 metadata 전체 apply 대신 `/spec/template`과 `/spec/replicas`를 JSON patch로 되돌린다. **두 파드를 원본으로 복원하고 rollout/실제 ROS 응답을 확인한 후** 아래 명령으로 MPS를 중지한다.
```bash
systemctl --user disable --now cj-cuda-mps.service
```
실행 중 MPS 클라이언트를 남겨둔 채 daemon을 먼저 종료하지 않는다. baseline 브랜치/이미지/소스는 변경하지 않았으므로 이 실험과 별개로 재현할 수 있다.

Spark에서 재실행할 때는 `bash ~/cj-serving/mps-green-v1/launch_deploy.sh`를 사용한다. 이 스크립트는 ROS 환경을 먼저 source하고, helper 경로를 **기존 PYTHONPATH 앞에 추가**한다. PYTHONPATH를 helper 경로만으로 덮어쓰면 호스트 health 클라이언트에서 `rclpy`를 찾을 수 없다. 정상 배포 상태에서의 중복 배포 대신 기존 설정/backup 조건을 먼저 확인한다.
