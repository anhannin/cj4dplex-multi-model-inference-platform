# Green Context 기능 검증과 운영 복구 — 2026-11-03

## 결과

현재 DGX Spark GB10 / CUDA13.0 / PyTorch2.9 NVIDIA 이미지에서 기능 검증 성공.
프레임워크 업그레이드나 외부 Python 패키지 설치 없이 기존 pybind11와 nvcc로
작은 Driver API 어댑터를 만들었다. 모델 및 라이브러리 원본은 수정하지 않았다.

- 실제 장비:48SM, 최소 분할8SM, co-scheduled 정렬8SM.
- 동일 자원을 한 번 분할하여16SM과 나머지32SM을 생성했다.
- CUDA SM-ID probe에서16/32개 ID를 모두 관측했고 두 집합은 겹치지 않았다.
- 두 Green Stream에서512×512 PyTorch 행렬곱·ReLU가 기본 Stream 결과와 오차0.
- Qwen3.5-9B:16SM Green Stream에서32토큰 생성 성공, 기본 실행과 token 완전 일치.
  실제 generate 구간 CUDA 커널62,606개 모두 CUPTI greenContextId가 nonzero.
  FLA gated-delta와 causal-conv 커널도 각각768개 모두 해당 Green Context였다.
- YOLO26l:16SM Green Stream에서 stock predict 성공, 같은 bus 이미지의 검출5개,
  좌표/확률/클래스 최대 차이0. 실제 predict 커널845개 모두 Green Context였다.
- 독립 프로세스가 같은16+32 분할 정의에서 서로 다른 쪽을 선택한 SM-ID 관측은
  생성 순서를 바꾼3회 모두 비중복이었다. 이는 현재 환경의 관측이지 전역 예약 보장이 아니다.

검증 범위는 작은 Tensor와 Qwen 한 프롬프트·출력32토큰, YOLO 이미지1개다.
모든 입력 길이/출력 길이/라이브러리 코드 경로의 호환성·정확도를 입증한 것은 아니다.
새 Green Context 이미지나 서비스 배포는 만들지 않았다. 기존 Pod는 Green을 쓰지 않는다.

## 가장 중요한 제약: SM 분할과 프로세스 간 동시 실행은 별개

고정된 수의 integer 연산을 수행하는 별도 CUDA 마이크로벤치마크로 확인했다.
clock 기반 busy-wait가 아니라 실제 고정 반복 연산이며, timed 구간의 메모리 할당은
제거하고 CUDA lazy init을 예열했다. native 호출은 GIL을 해제한다.
두 프로세스의 solo 기준은 서로 순서대로 측정해 기준부터 경쟁하지 않도록 했다.

| 조건 | 작업0 단독 | 작업1 단독 | 두 작업 함께 |
|---|---:|---:|---:|
| 같은 프로세스의 두 Green Context/Stream | 약190.9ms | 약190.9ms | 약191.0ms |
| 서로 다른 CUDA 프로세스 | 약190.9ms | 약190.9ms | 약398.8ms |

3회 반복에서 같은 프로세스의 동시 wall time은 단독 합의 약0.50배,
다른 프로세스는 단독 합의 약1.04배였다. 현재 설정의 분리 프로세스에서는
실질적인 동시 실행 이득이 관측되지 않았다.

이는 모든 GPU/드라이버/조건에서 Green의 프로세스 간 병렬 실행이 불가능하다는
일반 증명은 아니다. 다만 **현재 두 Pod에 SM quota만 붙여도 실행이 병렬화된다고
가정하면 안 된다는 직접 근거**다. Green Context는 비중복 SM만으로 동시 실행과
forward progress를 보장하지 않는다.

후속 선택:
1. 두 Pod와 프로세스 분리를 유지하려면 MPS 기본 기능/동시성부터 검증.
2. 순수 Green을 쓰려면 같은 프로세스의 두 Worker 구조를 별도 후보로 검토.
3. MPS+Green 조합은 지원·실제 자원 매핑을 검증한 뒤에만 후보로 취급.

구조를 바꾼다면 같은 새 구조의 Green OFF 기준선도 필요하다.
같은 프로세스의 실제 두 모델 동시 성능, Python GIL 영향, fault-domain 변화는 미검증이다.
모델 정확도·GPU 메모리/대역폭 격리·MIG 같은 독점 자원을 보장한 결과가 아니다.

## 구현

diagnostics/green_context/green_bridge.cu:
- cuDeviceGetDevResource → cuDevSmResourceSplitByCount → resource descriptor
  → cuGreenCtxCreate → cuGreenCtxStreamCreate.
- 동일 split의 첫 파티션과 remainder를 사용한다. 각 모델이 별개로32/16SM만
  요청하면 비중복이 보장된다고 가정하지 않는다.
- Stream의 실제 owner를 cuStreamGetGreenCtx로 검증한다.
- PyTorch는 ExternalStream으로 연결하고 입력 순서·완료를 명시적으로 동기화한다.
- GPU reset/primary-context reset은 사용하지 않는다.
- 현재 어댑터는 실험용이다. 운영 적용 전 thread/lifetime/error handling과
  선택 Stream을 완료시키는 지연시간 계측 의미를 다시 검증해야 한다.

실험 버전1 source/binary는 source-version1 및 Spark src/version1에 보관했다.
버전2는 고정 연산 동시성 probe용이며, 실제 모델 기능 검증은 버전1을 사용했다.
컴파일은 ARM64/SM121용이므로 로컬 x86 PC에서 import하는 모듈이 아니다.
실행은 Spark의 baseline 컨테이너 이미지에서 한다.

## 별도로 발견한 서비스 장애와 복구

실험 말미의 기본 ROS health 확인에서 타임아웃이 발생했다.
Pod Ready1은 초기 모델 로딩만 의미했으며 실제 요청 전달을 보장하지 않았다.

직접 관측:
- 두 서비스 로그에 새 요청 processing_started가 없었고 GPU Worker는 대기 중이었다.
- RTPS endpoint는 보였지만 실제 데이터가 전달되지 않았다.
- 두 프로세스의 /proc/1/maps에서 서버 Fast DDS shm buffer/port가 deleted 상태였다.
  사용자1000의 LTTNG 공유 파일도 삭제됐고 root 파일은 남아 있었다.
- 호스트의 RemoveIPC는 yes, avees Linger는 no였다.

이 상태는 마지막 로그인 세션 종료 시 UID1000의 IPC를 지우는 logind 정책과 일치한다.
특정 GPU 실험이 삭제를 일으켰다고 주장하지 않는다. 서비스에 마지막 성공 요청은
이전 작업에 있었으며, 이번 작업 시작 시 Ready만 확인했으므로 정확한 삭제 시각은 모른다.

복구:
- 전역 RemoveIPC=yes 및 GPU/드라이버 보안 설정은 유지.
- avees 계정만 sudo loginctl enable-linger avees 적용(no→yes).
- 같은 Deployment template·이미지로 두 Pod를 재생성해 삭제된 shm을 다시 만들었다.
- 기본 ROS 전송 경로의 실제 요청4건이 모두 성공했다.
- SSH 세션을 모두 닫고 user-manager의 별도 observer에서15초/45초 시점에
  State=lingering, Sessions=빈값, 서버 shm 파일2개 및 POSIX marker 유지 확인.
- 이후 재접속 후 요청4건·UUID 분리·결과 이미지2장 검증도 PASS.
- 임시 SSH keepalive/observer는 종료했으며 직접 만든 marker만 제거했다.

계정 linger는 로그아웃 후 user-manager/IPC 수명에 영향을 주는 운영 설정 변경이다.
GPU 최적화와 구분한다. 롤백은 sudo loginctl disable-linger avees지만,
대체 IPC 수명 설계 없이 되돌리면 장애가 재발할 수 있어 무조건 실행하지 않는다.
장기 운영에서는 전용 서비스 UID/IPC 설계와 실제 E2E health 탐지가 필요하다.
이는 자동 장애 복구·SLO 달성을 구현한 결과는 아니다.

복구 직후 기존 audit harness가 빠른 YOLO 요청 하나를 관측하지 못한 경우도 있었다.
네 클라이언트 응답은 모두 ok였지만 observer의 discovery 전 writer가 끝나는
테스트 race였다. 원본/실패 기록을 보존하고, 진단용 client 복사본만 server와
observer 두 subscriber가 매칭된 뒤 publish하도록 해 재검증했다.
운영 client·model·baseline 측정 코드는 변경하지 않았다.

## 자료

- verification.json: 통합 검증 요약
- raw/green-torch16*: Native+Tensor 기능/원시 Nsight
- raw/model-green-coverage.json: 실제 모델 커널의 Green 경로 검증
- raw/qwen-green16*, raw/yolo-green16*: 모델별 단일 기능 케이스
- raw/cross-process/: 독립 프로세스 SM-ID 관측
- raw/concurrency/: 고정 연산 동시성, 인퍼런스 성능 결과가 아님
- recovery/: 삭제 shm 증거·linger 전후·로그아웃 유지 검사·요청 검증
- health-before-recovery*: 원래 실패한 health 기록
- ../../diagnostics/green_context/: source, 빌드, probe, 분석·검증기
- Spark 원본: /home/avees/cj-green-context/20261103-v1

baseline Git 참조6a99fda와 기존 버전관리 파일은 보존했다.
새 실험 source/결과는 로컬 experiments/green-context 작업트리와 Spark에 보관하며,
이번 작업에서 GitHub/Docker Hub에 새 결과를 push하지 않았다.
