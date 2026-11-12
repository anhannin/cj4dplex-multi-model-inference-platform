# Nsight Systems 진단 — 최적화 전 GPU 실행 경로

## 수행 범위와 결론

사용자가 요청한 **1단계: 짧은 프로파일링만** 수행했다.
MPS / SM 제한 / Green Context / 모델 backend / 정밀도 / Queue 정책은 변경하지 않았다.
원본 배포 template·이미지·Node 명령을 복구했고 두 Pod Ready1 및 요청 성공을 확인했다.
baseline Git 참조는6a99fda 그대로이며 원본 버전관리 파일도 변경하지 않았다.

**GPU 실행 경로의 간섭을 우선 조사해야 한다는 근거는 확보했다.**
그러나 SM 연산량 포화, DRAM 대역폭 포화, GPU context 스케줄링 중 어느 것이
주원인인지는 이번 trace만으로 확정하지 않았다. 최적화를 적용하거나 개선을 주장한 결과가 아니다.

## 방법

- 같은 baseline 이미지·GB10 한 대·공유 슬롯2·모델별 Worker1/FIFO8/C1 유지.
- 컨테이너에 이미 포함된 Nsight Systems2025.5.1 사용. 호스트2025.3.2와 섞지 않고
  export/stats도 동일 이미지의2025.5.1에서 수행했다.
- 원본 Node는 수정하지 않고 diagnostic 복사본에 capture-file gate와 NVTX만 추가했다.
  stock generate()/predict(), 인수, 모델 가중치와 CUDA 라이브러리는 그대로다.
- 워밍업5회 및 별도 예열 요청 후 cudaProfilerApi로 짧은 구간만 수집.
- CUDA API / GPU kernel / memcpy / NVTX / OS runtime trace. CPU sampling·CPU context
  switch·SM/DRAM hardware counter는 수집하지 않았다. kernel paranoid4 설정을 유지하고
  SYS_ADMIN/privileged 추가, 보안 설정 완화, 드라이버 변경을 하지 않았다.
- 두 모델은 모든 진단 구간에 상주했다. 진정한 단독 Pod 측정은 이번 진단에 없다.

| 구간 | Qwen 요청 | YOLO 요청 | 수집 길이(약) |
|---|---:|---:|---:|
| Qwen만 활성 | 2 | 0 | 25초 |
| YOLO만 활성 | 0 | 100 | 4초 |
| 둘 다 활성 | 2 | 780 | 34초 |

Qwen은 동일 프롬프트 순서·실제 출력128토큰, YOLO는 같은 이미지2개 순환이다.
Qwen의 입력·출력 문자열은 두 활성 조건에서 모두 같았다.
본 수집884건 모두 성공, GPU kernel 이벤트 총1,743,320개다.
6개 리포트의 NVTX 구간 이름·요청 수·kernel launch correlation을 검증했다.
확인된 dropped/data-lost/buffer-overflow 진단 메시지는 없었다.

**이 수치는 프로파일러가 붙은 짧은 진단값이다. 기존 Baseline v1 수치를 대체하지 않는다.**

## 관측1: Qwen 지연 증가는 GPU 커널 구간 증가와 동반

| 항목 | Qwen만 활성 | 동시 활성 |
|---|---:|---:|
| generate NVTX 평균 | 11.704초 | 16.136초 |
| 요청당 GPU kernel 구간 합집합 | 11.012초 | 14.912초 |
| 요청당 kernel 수 | 249,930 | 249,930 |
| 해당 커널 구간이 generate를 덮는 비율 | 94.1% | 92.4% |

GPU kernel 수는 같고 그 구간의 elapsed time이 늘었다.
GPU elapsed 합의 약95.9~96.4%는 BF16 GEMV 계열 kernel 두 변형에서 관측되었다.
주요 두 변형의 평균 kernel elapsed는 각각 약361→490us,302→412us였다.

해석:
- 입력이나 토큰 수 증가, ROS 애플리케이션 큐 증가로 설명할 상황은 아니다.
- GPU 커널 구간 자체 및 그 실행 대기를 우선 분석할 근거다.
- kernel start~end 구간의 합집합은 SM active cycles/occupancy가 아니다.
  다른 프로세스와의 스케줄링 영향과 메모리 대역폭 영향을 이 지표로 분리할 수 없다.
- 커널 개수 기준으로 작은 grid가 많지만,48SM보다 적은 block을 가진 launch가
  차지하는 GPU elapsed 합은 약2.4~3.0%뿐이다. 개수만 보고 GPU가 대부분 비어 있다고
  판단하지 않는다. 반대로 큰 grid만으로 높은 실제 SM occupancy를 입증하지도 않는다.

## 관측2: YOLO는 커널 실행 전 시각차와 동기화 대기가 크게 증가

| 항목 | YOLO만 활성 | 동시 활성 |
|---|---:|---:|
| predict 전체 NVTX 평균 | 10.370ms | 30.097ms |
| 요청당 GPU kernel 구간 합집합 | 6.188ms | 8.436ms |
| 나머지 구간(순수 CPU 시간이 아님) | 4.182ms | 21.661ms |
| kernel별 launch API 반환→시작 시각차 평균 | 0.622ms | 5.492ms |
| 같은 시각차의 kernel별 p95 | 1.510ms | 9.107ms |
| 요청당 kernel 수 | 845 | 845 |

추가 관측:
- cudaDeviceSynchronize CPU API 구간 합은 요청당 약0.479→11.428ms.
- cudaLaunchKernel_v7000 CPU API 호출 평균은 약3.22→3.84us로, 반환 이후 시각차 증가에
  비해 변화가 작았다.
- 평균 애플리케이션 Queue 대기는 약0.304→0.768ms로 작았다.

해석:
- 모델 forward만의 변화가 아니라 GPU 명령 실행 전 대기와 완료 동기화가 섞여 있다.
- launch→kernel start에는 동일 CUDA stream의 선행 작업 의존성과 GPU 스케줄링이
  포함된다. 이 값을 GPU context-switch 비용이나 SM 대기만으로 부르지 않는다.
- API 반환 전에 GPU kernel이 시작될 수 있어 음수 시각차를 보존했다.
  API entry 기준에서도 극소수 us 수준 음수가 있어 clock correlation 정밀도 한계를
  함께 고려한다. ms 규모 비교를 미세 ns 정밀도 주장으로 해석하지 않는다.
- kernel별 시각차를 요청마다 합산하면 안 된다. 여러 kernel의 queue 구간은 겹친다.
- cudaDeviceSynchronize API의 긴 구간은 CPU가 GPU 완료를 기다린 관측이다.
  동기화 호출 자체가 원인이라 단정하거나 무조건 제거하면 안 된다.

## 관측3: 명시적 memcpy의 device elapsed는 작음

Qwen 두 요청 기준:
- Host→Device: 총816bytes, device elapsed 약0.008ms.
- Device→Host: 총4,768bytes, device elapsed 약0.868ms.
- Device→Device: 약12GiB, device elapsed 약42.098ms.
- 전체 memcpy device elapsed: 약42.975ms, 동시 조건 약48.538ms.

반면 cudaMemcpyAsync의 CPU API 구간 합은 약13.40→18.36초였다.
**API에 머문 시간을 순수 데이터 복사시간으로 해석하면 안 된다.**
GPU 선행 작업의 완료 대기가 포함될 수 있다. scalar 결과의 CPU 관측 등
생성 제어 동작도 있으며, 이번에는 임의로 제거하지 않았다.

YOLO 명시적 memcpy device elapsed는 요청당 약0.030→0.083ms였다.
따라서 이번 자료는 H↔D 대량 복사 자체를 최우선 병목으로 지목하지 않는다.
단, 커널 내부의 모델 weight/activation 메모리 접근은 memcpy 이벤트가 아니므로
이 결과가 DRAM 대역폭 병목을 배제하는 증거는 아니다.

## 확인하지 못한 것

- SM occupancy/연산 throughput 및 DRAM 실제 bandwidth counter.
- GPU context 전환의 직접 trace와 그 비용.
- CPU perf sampling·Python CPU 계산/GIL·CPU scheduling의 상세 분리.
- Unified Memory fault/migration: driver/configuration에서 trace 미지원 경고.
- ROS publish→클라이언트 callback의 긴 tail 원인. 호스트 클라이언트는 GPU trace 대상이 아니다.
- 짧은 N2/N100 한 번의 진단으로 안정적인 p95/SLO나 통계적 인과성을 입증하지 않는다.

## 다음 실험에 대한 판단 — 아직 실행하지 않음

우선순위는 **MPS 제한 없는 조건의 A/B**다.
GPU 명령 실행 간섭과 완료 대기가 달라지는지 보고, 그 뒤 자원 상한/SM 분할을
검토하는 편이 타당하다. 현재 자료로 Green Context/SM 분할을 바로 선택할 근거는 부족하다.
특히 GEMV 지연이 memory bandwidth와 관련된다면 SM만 분할해도 해결되지 않을 수 있다.
MPS도 반드시 좋아진다고 가정하지 않는다.

## 수집 제어 문제와 복구 기록

원본 controller-status.json의 FAIL을 지우지 않았다. 이는 아래 수집 제어 문제 기록이며,
최종 데이터 유효성은 별도 verification.json으로 검증했다.

1. 최초 호스트 클라이언트의 ROS PYTHONPATH 누락: 요청 전에 실패, 자동 원복.
   ROS 환경 source 및 기존 PYTHONPATH 보존을 수정하고 회귀 테스트를 추가했다.
2. 반복 capture report가 세션 종료 시 완성되는 동작: 첫 구간 후 파일 대기 timeout,
   자동 원복. 작은 독립 테스트로 다중 구간의 파일 생성·kill=none을 확인했다.
3. 최종 실행은 세 구간을 모두 수집했다. 이후 이미 자동 종료된 profiler 세션에
   shutdown을 보내 비정상 반환을 오류로 처리했다. 원본 배포 자동 원복은 성공했다.
   저장된 리포트6개를 **CPU-only runc Docker**로 export/stats하여 전부 복구·검증했다.
   향후 스크립트는 이미 종료된 세션과 완성된 report3개를 허용하도록 테스트·수정했다.

초기 interactive launch 경로의 작은 CUDA probe에서는 OOM이 한 번 발생했다.
cudaProfilerApi smoke와 실제 모델 capture 경로는 정상 동작하여 해당 방식만 사용했다.
이를 서비스 모델의 OOM 장애 재현·복구 실험으로 주장하지 않는다.

## 복구와 무결성

- 원래 Deployment spec.template과 replicas1 정확히 일치.
- 임시 ConfigMap/진단 mount/진단 실행 명령 제거 확인.
- 원래 이미지 ID와 Node 소스 SHA-256 일치, 실행 명령 /app/ros2/*_node.py.
- 최종 두 baseline Pod Ready1, 재시작0. 진단 과정에서 의도적인 Pod 재생성은 있었다.
- 원복 후 문서화된 워밍업 및 네이티브 요청 확인 PASS.
- MPS daemon 없음. 기존 GPU 공유 슬롯 설정과 CPU/RAM hard-limit 정책 유지.
- baseline Git 브랜치 및 원본 모델/측정 소스는 그대로다.
- raw .nsys-rep/.sqlite는 로컬·Spark에 보관하며 Git에서는 제외한다.
- 초기 실패 시도의 상세 기록도 보존했다. 실패 시도 raw reports는 Spark에 남겼다.

## 파일

- verification.json: 최종 수집 유효성·복구 검증 (controller 종료코드와 분리)
- restoration-verification.json: 라이브 원복 증거
- comparison.json / analysis.json: 정규화 지표 및 상세 집계
- copy-directions.json: 방향별 명시적 memcpy
- reports/{qwen,yolo}/capture.{1,2,3}.nsys-rep: 원시 리포트
- reports/{qwen,yolo}/{qwen-only,yolo-only,concurrent}.sqlite: export
- *-kernels.csv: kernel별 호출 수·elapsed 통계
- evidence/*-stats.csv: 원본 Nsight 통계
- clients/: 실제 요청·응답·시간·워밍업 구분
- ../../diagnostics/nsight/: 생성기, 제어·후처리·분석 코드
- Spark 원본: /home/avees/cj-nsys-diagnostics/20261103-v1
