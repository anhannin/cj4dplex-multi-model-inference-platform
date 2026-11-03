# Spark 단일 노드 Kubernetes

## 설치 상태

- 노드: `spark-e6d6` (`192.168.24.204`, ARM64)
- Kubernetes: **v1.37.2**, kubeadm 기반, control-plane/worker 겸용 단일 노드
- 런타임: containerd **2.2.1**, Kubernetes 전용 `containerd-k8s.service`
- CNI: Flannel **v0.28.10**
- NVIDIA device plugin: **v0.20.1**, `RuntimeClass: nvidia`
- GPU allocatable: 설치 직후 `nvidia.com/gpu: 1`; 모델 배포에서는 **`nvidia.com/gpu.shared: 2`**로 변경. 물리 GPU는 여전히 1개.

설치 스크립트는 이 Spark의 주소/환경을 대상으로 하며, 기존 클러스터를 덮어쓰지 않도록 거부한다.
이미 설치된 서버에서 다시 실행하거나 다른 장비에 그대로 실행하면 안 된다.

## 바로 확인하기

```bash
ssh avees@192.168.24.204
kubectl get nodes -o wide
kubectl get pods -A
kubectl describe node spark-e6d6
```

관리자 kubeconfig는 Spark의 `~/.kube/config`에만 있고 권한은 `600`이다.
관리자 인증서/키, bootstrap token, 비밀번호는 이 저장소에 넣지 않는다.
로컬 PC의 kubectl 접근 설정이나 API 외부 공개는 수행하지 않았다. Spark에 SSH로 접속해 사용한다.

## 기존 환경 보호

Docker가 쓰는 containerd와 Kubernetes 런타임을 분리했다.

| 항목 | Kubernetes 전용 경로 |
|---|---|
| 서비스 | `containerd-k8s.service` |
| 설정 | `/etc/containerd-k8s/config.toml` |
| NVIDIA drop-in | `/etc/containerd-k8s/conf.d/99-nvidia.toml` |
| CRI socket | `/run/containerd-k8s/containerd.sock` |
| 상태 | `/run/containerd-k8s` |
| 이미지·snapshot 저장소 | `/var/lib/containerd-k8s` |

- 기존 `/etc/containerd/config.toml`, `/etc/docker/daemon.json` 해시를 보존했고 Docker 서비스를 재시작하지 않았다.
- 기존 `cj-qwen-dev`, `cj-yolo-dev` 컨테이너 유지 및 CUDA 행렬 연산 재검증 통과.
- 호스트 NVIDIA 드라이버/Toolkit/OS를 업그레이드하지 않았다.
- 호스트 swap을 유지하고 kubelet의 공식 `failSwapOn: false`, `memorySwap.swapBehavior: NoSwap`를 사용했다.
- Pod CIDR `10.244.0.0/16`, Service CIDR `10.96.0.0/12`: 기존 LAN/Docker 대역과 분리했다.
- UFW를 끄지 않고 CNI 인터페이스/Pod 소스에 한정한 통신 규칙을 추가했다. 기존 SSH 규칙 유지.
- kubelet과 전용 containerd는 부팅 시 자동 시작하도록 설정했다. 실제 재부팅 시험은 수행하지 않았다.

Docker 이미지 저장소와 Kubernetes 이미지 저장소는 별개다.
따라서 현재 Docker에 있는 Qwen/YOLO 이미지는 Kubernetes에 자동으로 보이지 않는다.
모델 배포 시 registry 또는 전용 containerd의 `k8s.io` namespace로 별도 전달해야 한다.

## 검증 결과

증거: [`../results/k8s/`](../results/k8s/).

1. Node Ready, Flannel/CoreDNS/control-plane/system Pods 정상 실행.
2. 테스트 Pod에서 클러스터 DNS 조회 및 ClusterIP Service를 통한 HTTP 요청 성공(`DNS_HTTP_OK`).
3. `nvidia.com/gpu: 1`을 요청한 Pod가 스케줄·종료에 성공했고 `nvidia-smi`에서 GB10/Driver580.173.02 확인.
4. 기존 두 Docker 개발 컨테이너의 CUDA 행렬 연산 성공.
5. 시험용 `cj-validation` namespace는 결과 보존 후 삭제했다.

NVIDIA plugin은 GB10의 NVML memory size 조회에 `Not Supported` 경고를 남긴다.
GPU 등록/할당/visibility 시험은 통과했지만, 이 plugin의 memory size를 GPU 메모리 실측값으로 사용하면 안 된다.
Kubernetes Pod에서 Qwen/YOLO 추론이나 CUDA 연산 성능을 검증한 것은 아니며, GPU 시험은 할당/장치 인식 범위다.

## 시험 재현

`manifests/smoke.yaml`로 namespace, nginx Deployment, ClusterIP Service를 만든 뒤:

```bash
kubectl apply -f smoke.yaml
kubectl -n cj-validation rollout status deployment/smoke-web --timeout=180s
kubectl apply -f dns-http-smoke.yaml
kubectl -n cj-validation wait --for=jsonpath='{.status.phase}'=Succeeded pod/dns-http-smoke --timeout=180s
kubectl -n cj-validation logs dns-http-smoke
kubectl apply -f gpu-smoke.yaml
kubectl -n cj-validation wait --for=jsonpath='{.status.phase}'=Succeeded pod/gpu-smoke --timeout=180s
kubectl -n cj-validation logs gpu-smoke
# 로그 보존 후 자신이 만든 시험 namespace만 정리한다.
kubectl delete namespace cj-validation
```

위 YAML 경로는 서버 `/home/avees/cj-k8s/`에 준비돼 있다.

## 아직 하지 않은 것

- Qwen/YOLO의 Kubernetes 배포, API/Queue 구성, readiness/liveness 및 장애 복구 실험
- GPU time-slicing/MPS/Green Context, GPU Operator, Ingress, 외부 포트 공개
- HA, 네트워크 정책, 저장소 provisioner, 보안/CVE 검토, 장시간 안정성·재부팅 검증

현재 GPU resource는 1개이며 공유 설정이 없다. 각자 GPU 1개를 요청하는 모델 Pod 두 개를
동시에 배치할 수 있는 상태라고 해석하면 안 된다. GPU 공유/배치 설계는 별도로 결정해야 한다.

## 설치·운영 기록

- root-only 설치 로그: `/var/log/cj-k8s-install.log` (kubeadm bootstrap 정보가 있어 저장소로 복사하지 않음)
- 설치/설정 파일: 이 폴더 `install/`, `manifests/`
- 공개 apt signing key 권한과 strict pipefail 환경의 버전 선택 파이프를 수정한 뒤 설치를 완료했다.
- Runtime sandbox image는 kubeadm 권장 `registry.k8s.io/pause:3.10.2`로 정렬했다.
- AI Coding Assistant(Codex)가 설치 스크립트·manifest·검증 및 문서를 작성했다.

공식 참고:
- [kubeadm 설치](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/install-kubeadm/)
- [containerd와 systemd cgroup](https://kubernetes.io/docs/setup/production-environment/container-runtimes/)
- [Flannel](https://github.com/flannel-io/flannel)
- [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin)
- [NVIDIA runtime 설정](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)

## ROS 2 모델 배포

두 모델의 Deployment, 공유 GPU 설정, 검증 및 롤백 절차는 [serving/README.md](serving/README.md)를 참고한다.
기존 설치 manifest를 무심코 재적용하여 공유 설정을 제거하지 않는다.
