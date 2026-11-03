# Baseline v1 — 최적화 전 보존본

이 브랜치는 **2026-11-03에 측정한 최적화 전 기준선**을 보존한다.
최적화는 별도 브랜치에서 수행하며 이 기준선의 코드·입력·결과를 덮어쓰지 않는다.
이미지 ID와 소스 해시는 [MANIFEST.json](MANIFEST.json)이 기준이다.

## 보관 내용

| 항목 | 위치 |
|---|---|
| 실행 중인 Pod에서 직접 추출한 /app 전체 프로젝트 코드 | container-code/{qwen,yolo}/app/ |
| 개발용 원본 ROS Node | ../ros2/qwen_node.py, ../ros2/yolo_node.py |
| Spark의 클라이언트·측정기·Dockerfile 스냅샷 | host-code/ |
| 측정기·집계·실험 제어 코드 | ../benchmark/ |
| 라이브 Kubernetes에서 추출한 재배포용 설정 | deployment/ |
| 이미지 상세정보·패키지 버전·runtime 설정 | environment/ |
| 측정 결과·원시 응답·서버 로그·검증 | ../results/latency-baseline/ |
| 설치·빌드·이전 탐색 코드와 기록 | 루트 containers/, k8s/, scripts/, tests/, results/ |

container-code/는 이번 동결 시점의 **실제 실행 컨테이너**에서 추출했다.
루트 container_code/는 과거 개발 컨테이너의 라이브러리 열람용 스냅샷으로
별개이며 Git에서 제외된다. 외부 라이브러리·바이너리를 포함한 전체 실행 환경은
아래 실제 이미지 archive에 있다. 제3자 라이브러리를 직접 구현한 것으로 주장하지 않는다.

## 실제 컨테이너 이미지 보관 — Git 외부

model-images.tar는 두 runtime 이미지와 모든 이미지 레이어를 포함하는
Docker-save archive다. 크기 **19,781,231,104 bytes**로 Git에 넣지 않는다.

- Spark: /home/avees/cj-baseline-artifacts/20261103-v1/model-images.tar
- 로컬: /home/avees/cj-baseline-artifacts/20261103-v1/model-images.tar
- SHA-256: f69f895529d0655b0ac8ba38f766ac72e1ebe0795f5ccba9bb83f2d4b7cbaabe
- 두 위치의 파일은 동일 해시 검증 후 보존한다.
- GitHub에는 이미지 실물 대신 해시·이미지 ID·Dockerfile·복원 절차를 보관한다.

이미지 태그: cj-qwen-ros:9b-timing-v1 / cj-yolo-ros:26l-timing-v1.
Spark Docker에는 같은 ID의 baseline-20261103-v1 별칭도 추가했다.
archive에 포함된 태그는 원래 timing-v1 태그이며 복원 시 이 태그를 사용한다.
Docker config ID와 OCI manifest digest를 같은 값으로 취급하지 않는다.

### 복원

**현재 서비스에 그대로 실행하지 않는다.** 기존 모델을 먼저 정상 종료하고
ARM64 / NVIDIA driver / GPU runtime과 hostPath를 확인해야 한다.

    cd /home/avees/cj-baseline-artifacts/20261103-v1
    sha256sum -c SHA256SUMS

    # 일반 Docker로 불러오기
    docker load -i model-images.tar

    # 또는 별도 Kubernetes containerd에 불러오기
    sudo ctr --address /run/containerd-k8s/containerd.sock --namespace k8s.io images import --platform linux/arm64 model-images.tar

이미지 ID를 MANIFEST.json과 비교한 뒤 필요할 때 아래 순서로 배포한다.

    kubectl apply -f baseline/deployment/namespace.json -f baseline/deployment/runtimeclass.json -f baseline/deployment/gpu-sharing.json -f baseline/deployment/device-plugin.json
    kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset
    # Node allocatable nvidia.com/gpu.shared=2 등록도 확인한다.
    kubectl apply -f baseline/deployment/qwen.json -f baseline/deployment/yolo.json

환경 파일은 참고/복원 자료이며 기존 호스트 설정을 무조건 덮어쓰는 스크립트가 아니다.
라이브 object의 UID/resourceVersion/status 등은 재배포 manifest에서 제거했다.
실제 측정 때의 Pod/Deployment 정보는 결과 폴더에 별도로 보존되어 있다.

## 제외 범위

- **모델 가중치·테스트 원본 이미지는 Git/컨테이너 archive에 포함하지 않는다.**
  기존 Spark hostPath 파일은 그대로 보존되어 있으며 revision·해시·출처는 기록한다.
  다른 서버에서 복원하려면 해당 가중치·입력 파일을 별도로 준비해야 한다.
- /runtime 캐시는 qwen-runtime-cache.tar.zst / yolo-runtime-cache.tar.zst로 같은 외부
  백업 폴더에 보조 보관한다. 장비·driver 종속 캐시이므로 자동 복원하지 않는다.
  이는 보존 시점의 캐시 스냅샷이며 GPU 실행·큐 상태 체크포인트가 아니다.
  Ready 파일은 제외한다. 성능 재현 시에는 기록된 워밍업 절차를 적용한다.
- SSH 키, 비밀번호, kubeconfig/admin 인증서, API 토큰, .env, 과제 PDF,
  OMX 세션 기록, 로컬 가상환경 및 GPU 컴파일 캐시는 Git에 포함하지 않는다.
- 이미지 archive는 GitHub 업로드가 아닌 Spark/로컬 별도 파일 백업이다.

## 결과와 제약

[상세 보고서](../results/latency-baseline/README.ko.md)가 결과의 기준이다.
본 측정12,324건 성공, 같은 GPU의 다섯 조건, 모델별 closed-loop C1이다.
이는 고동시성/포화/SLO/장애 복구 검증이 아니다. SM 분할/MPS 최적화는 없다.
Qwen 재시작 전후 일부 문구 차이, 작은 표본과 순서 효과, CRI 회전 로그 복구 등
관측된 한계도 보고서에 그대로 보존했다.

## 검증·구현 범위

- 실제 컨테이너 Node 소스와 루트 소스 SHA-256 일치.
- 라이브 Pod imageID와 저장한 Docker 이미지 ID 일치.
- 결과 재집계·단위 테스트·Ruff 결과는 verification/에 보관.
- 이미지 전체 파일 SHA-256은 Spark 및 로컬에서 검증.
- AI Coding Assistant(Codex)를 ROS 서빙·계측·배포·검증·문서화에 사용했다.
  모델 알고리즘/프레임워크 원본을 변경한 것이 아니며, 수치는 Spark 실측 결과다.

## 소스/결과 파일 무결성

checkout 이후 저장소 루트에서 다음 명령으로 버전 관리 파일을 검증한다.

    sha256sum -c baseline/FILES.sha256

원본 로그의 CRLF·진행 표시·끝 공백은 수정하지 않았다.
.gitattributes는 checkout 시 파일 바이트를 보존하며 원시 결과의 공백 검사는 제외한다.
