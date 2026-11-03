# Kubernetes 모델 배포 검증 — 2026-11-03 KST

## 결과

- Spark 단일 노드에 Qwen3.5-9B / YOLO26l Deployment 각각 replicas=1, Recreate로 배포.
- 두 Pod 모두 Ready 1/1, restart 0. 기존 Docker 모델 컨테이너는 정상 종료 후 보존.
- NVIDIA device plugin 공유 참조 2개 등록. 두 모델 Pod에서 동일 GB10 UUID 확인.
- MPS / SM 분할 / 우선순위 / 모델 간 스케줄러는 미적용.
- 네이티브 Spark Python 클라이언트 동시 요청 4건 성공: Qwen 2, YOLO 2.
- 고유 UUID 4개, 응답 혼선 0, 결과 이미지 2장 저장 및 원본 이미지 무변경.
- Qwen 첫 요청 처리 구간 안에 YOLO 요청 2건이 시작됨. 모델별 독립 실행 확인.
- 모델당 request 구독자 1개, 응답 publisher 정리 확인.
- 컨테이너 내 실행 소스와 로컬 소스 SHA256 일치.
- 로컬 단위/구조 테스트 54개 통과.

## 주요 자료

- verification-summary.json: 검증 요약
- pods-final.json / deployments-final.json: 실제 클러스터 상태
- node-final.json / device-plugin.log: 공유 GPU 등록 상태
- qwen-gpu.txt / yolo-gpu.txt: 동일 물리 GPU 확인
- qwen.log / yolo.log: 로딩·요청 시작·종료 로그
- clients/summary.json: 실제 클라이언트 검증 결과
- clients/bus.png / clients/zidane.png: 객체 검출 결과 이미지
- unit-tests.log / lint.log: 로컬 검사
- deploy-initial-resource-race.log: 최초 배포 스크립트 대기 조건 문제 기록

## 구현 변경과 한계

모델 추론 코드는 그대로 유지하고, 각 Node에 startup/readiness probe용
컨테이너 전용 ready-file 생성/삭제만 추가했다. 모델 로딩 및 요청 구독 생성 후
ready 상태가 된다. 이 신호는 워커 hang 탐지나 ROS traffic 차단을 보장하지 않는다.

device-plugin Pod가 Ready가 되어도 Node allocatable 갱신은 아직 끝나지 않을 수
있었다. 최초 스크립트의 즉시 검사는 실패했으며, 공유 GPU 2개 등록을 최대 60초
대기하도록 수정 후 성공했다. 모델 Pod 장애나 추론 실패는 발생하지 않았다.

이 테스트는 배포 및 기능 확인이다. SLO 검증이나 성능 baseline이 아니다.
새 emptyDir의 Triton 캐시에서 시작했으므로 Qwen 첫 요청에는 커널 컴파일이
포함된다. 성능 실험에서는 동일 입력·부하 및 명시적 warmup 조건을 별도로 정해야 한다.

메모리/CPU는 requests만 설정하고 hard limit은 두지 않았다. 공유 슬롯은 VRAM,
SM, 실행 시간의 절반 보장이 아니다. hostNetwork/hostIPC 및 hostPath 사용은
신뢰된 단일 서버 실험 조건이며, 멀티테넌트 보안·고가용성을 구현한 것은 아니다.
장애 주입·복구 실험도 아직 수행하지 않았다.

## 서버에서 확인

```bash
kubectl -n cj-inference get deployments,pods -o wide
kubectl -n cj-inference logs deployment/qwen --tail=20
kubectl -n cj-inference logs deployment/yolo --tail=20
```

배포 manifest와 재현/롤백 절차: ../../k8s/serving/README.md
