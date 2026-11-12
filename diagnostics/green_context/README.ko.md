# CUDA13 Driver API Green Context 실험

실행 대상은 Spark ARM64/GB10이다. 현재 baseline 이미지·PyTorch를 유지한다.
production 모델/라이브러리를 patch하지 않으며 기능·실행 경로 검증용 하네스다.

- green_bridge.cu/build.sh: pybind11 C++/CUDA 모듈, 자원 분할·Stream·SM-ID probe.
- probe.py/validate.py: 작은 Tensor·16/32SM 배정 및 수치 검증.
- qwen_model_probe.py/yolo_model_probe.py: 원본 generate/predict 호출의 Green Stream 검증.
- verify_nsys.py: NVTX 이름만 믿지 않고 CUPTI greenContextId를 검증.
- cross_process_probe.py: 독립 프로세스의 상보 SM-ID 관측(전역 예약 보장 아님).
- concurrency_probe.py: 고정 연산으로 같은/다른 프로세스의 실행 중첩 비교.
- ncu_probe.py/ncu_analysis.py: counter 접근 사전검사·누락 지표 보존·집계.

배포 전제조건: Driver API 실제 지원, 동일 split의 서로 다른 resource 선택,
Worker thread/Stream의 정확한 연결, Tensor 수명/동기화, 모든 내부 kernel 경로 확인.
Green은 memory bandwidth 또는 다른 default context의 자원 접근을 차단하지 않는다.

같은 프로세스 positive control과 달리 현재 분리 프로세스에서는 실제 병렬 이득이
관측되지 않았다. 두 Pod에 단순 적용하지 말고 MPS/공유 프로세스 구조를 별도 검증한다.
운영용 adapter와 latency/SLO benchmark를 완성했다고 주장하지 않는다.

실험 source 버전1은 실제 모델/Stream 기능 검증, 버전2는 fixed-work probe 추가본이다.
Spark의 /home/avees/cj-green-context/20261103-v1/src/version1에 당시 binary/source가 있다.
기존 report를 덮어쓰지 않는다. 복제 시 새 출력 폴더·파일명을 사용한다.

결과: ../../results/green-context/README.ko.md 및 ../../results/nsight-compute/README.ko.md.
실제 서비스 원본은 baseline6a99fda 그대로이며 새 실험은 원격 push하지 않았다.
