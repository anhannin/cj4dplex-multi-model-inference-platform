# Baseline 대표 커널의 Nsight Compute 분석 — 2026-11-03

## 결론

기존 Nsight Systems에서는 동시 실행의 GPU launch 대기와 커널 elapsed 증가를 관측했다.
이번에는 같은 baseline 이미지·Qwen3.5-9B BF16/SDPA·stock generate로 대표 GEMV를
하드웨어 카운터 진단했다. **SM 연산 파이프가 포화됐다는 단순 설명보다는,
메모리 의존 대기와 낮은 latency hiding을 먼저 조사할 근거**가 생겼다.
모든 지연 증가의 유일한 원인을 확정하거나 최적화 성능을 입증한 것은 아니다.

## 방법

- Nsight Compute2025.3.1, CUDA13.0, torch2.9 NVIDIA baseline 이미지.
- 서비스 Pod를 바꾸지 않고 별도 프로세스에서 동일 cached weights·프롬프트
  (입력23토큰)·출력128토큰·greedy/use_cache/TokenClock으로 실행.
- 원래 서비스 모델들은 resident/idle이며 별도 진단 모델을 추가 로드했다.
  따라서 이 실행의 E2E 시간은 기존 baseline 요청 지연시간이 아니다.
- 처음6개 GEMV를 확인한 뒤 실제 layer0 MLP up/down에 NVTX hook만 추가하여
  decode의 대표 GEMV2개를 선택했다. 모델 입력·출력·연산은 변경하지 않았다.
- SpeedOfLight, LaunchStats, Occupancy, SchedulerStats, WarpStateStats,
  MemoryWorkloadAnalysis. 선택2개에17pass kernel replay.
- cache-control=all, clock-control=none. 캐시 flush/replay가 있는 진단이므로
  커널 duration/L2 hit 값을 실제 서비스의 비계측 정상 값으로 대체하지 않는다.
- Counter 수집은 별도 read-only/network-none Docker에만 CAP_SYS_ADMIN 부여.
  추가 capability 없는 테스트는 ERR_NVGPUCTRPERM으로 거부됨을 확인했다.
  전역 RmProfilingAdminOnly=1 정책은 변경하지 않았다.
- 모델·가중치·측정 source·기본 배포·MPS/MIG는 변경하지 않았다.

## 대표 MLP 결과

| 지표 | up_proj | down_proj |
|---|---:|---:|
| weight shape | 12288×4096 | 4096×12288 |
| Compute(SM) Throughput | 8.69% | 10.88% |
| Registers per thread | 164 | 164 |
| Theoretical occupancy | 25% | 25% |
| Achieved occupancy | 24.43% | 24.46% |
| 평균 active warps / scheduler | 2.94 | 2.94 |
| 평균 eligible warps / scheduler | 0.05 | 0.07 |
| No Eligible | 95.72% | 94.25% |
| L2 hit rate | 1.63% | 1.84% |
| Long-scoreboard 기여율 | 59.82% | 47.14% |
| LG-throttle 기여율 | 26.68% | 36.63% |
| Local spilling requests | 0 | 0 |
| DRAM Throughput | 미제공 | 미제공 |

Long-scoreboard/LG-throttle 비율은 평균 warp issue 간격에 대한 stall 기여율이며
프로그램 전체 wall time 비율이 아니다. raw counter와 계산은
raw-stall-and-representativity.json에 남겼다.

샘플과 같은 BF16 GEMV launch geometry는 이전 baseline Nsight Systems의
GPU 커널 elapsed 합에서 각각 약42.64%,15.83%(합58.48%)를 차지했다.
동일 geometry 그룹은 여러 layer/연산을 포함할 수 있으며, 모든 커널을 이번에
counter 측정한 것은 아니다. GPU elapsed 비율을 E2E 비율로 바꾸지 않는다.

## 해석

관측 사실:
- 샘플의 SM 처리율이 낮고 발행 준비가 된 warp가 드물었다.
- 높은 register 사용량이 theoretical occupancy25%의 제한 요인으로 보고됐다.
- L1TEX(local/global/texture 등) 의존을 기다리는 long-scoreboard와
  local/global memory instruction queue 관련 LG-throttle 신호가 컸다.
- spilling 요청은0이므로 무조건 register spill을 원인으로 지목하지 않는다.
- default와 counter 실행의 생성 token은 일치했다.

합리적 가설:
- 해당 대표 GEMV는 연산 파이프를 충분히 채우기보다 메모리 응답/의존을 기다리고,
  동시에 준비된 warp가 적어 이를 숨기기 어려운 latency-bound 패턴이다.
- 단순히 GPU utilization이 높다는 이유로 SM 산술 연산 포화라 할 수 없다.
- SM 개수만 줄이면 근본 문제가 해결된다고 가정할 수 없다.

미확정:
- 이번 데이터에는 DRAM 관련 raw metric/throughput이 없어 실제 LPDDR 대역폭
  포화 여부를 판정하지 못했다. Memory Throughput이라는 종합 지표를 DRAM
  throughput으로 바꾸거나 누락 값을0으로 채우지 않았다.
- cache-control=all은 L2 hit에 영향을 준다. 위 L2 hit는 replay 조건의 관측값이다.
- 정확한 stalled SASS source 위치에는 추가 PC sampling이 필요하다.
- 동시 서비스 지연에는 context/stream 스케줄링·캐시·공유 메모리 경로가 함께
  작용할 수 있다. 단독 대표 커널 counter가 동시 지연의 유일 원인 증명은 아니다.

## 다중 프로세스 실행 제약과 연결

별도 Green 실험에서 같은 프로세스의 두 Green Stream은 고정 연산을 병렬 처리했지만,
분리 프로세스는 거의 직렬 합의 시간이 걸렸다.
이는 이전 Nsight Systems의 커널 실행 전 대기 증가와 함께 고려해야 할
GPU 실행 경로 제약이다. CUDA 요청 큐와 ROS 애플리케이션 Queue는 구분한다.

현재 두 Pod 구조를 유지하려면 MPS 기본 기능/동시성부터 검증하는 방향이 합리적이다.
순수 Green의 같은 프로세스 구조는 별도 topology baseline·GIL·fault-domain 검증이 필요하다.
아직 MPS 또는 새로운 서비스 구조를 적용하지 않았다.

## 운영 복구와 결과 사용 범위

마지막 서비스 확인에서 Fast DDS shared-memory 삭제로 요청이 전달되지 않는
별도 운영 장애를 발견했다. GPU 진단은 ROS endpoint를 쓰지 않았으므로 기능 결과와
구분한다. 원본 이미지로 Pod를 재생성하고 avees linger를 활성화하여 SSH가 없는
상태의 IPC 유지 및 재접속 요청 성공까지 검증했다.
상세 변경/실패 기록은 ../green-context/README.ko.md 및 recovery/에 남겼다.
GPU/driver 보안 정책과 baseline source는 유지했고, 운영 lifecycle 변경은 명시했다.

## 파일

- targeted-mlp-summary.json: friendly counter·원본 규칙
- raw-stall-and-representativity.json: raw stall 계산·baseline geometry 대응
- first-six-summary.json: 초기6개 GEMV 탐색(전체 대표성 보장 없음)
- raw/qwen-baseline-mlp*.csv, *.ncu-rep, *.json: 원본 report·출력 검증
- raw/counter-probe*: counter 권한/도구 지원 사전검사
- ../../diagnostics/green_context/ncu_analysis.py: 누락 값 보존 parser·분석
- ../../diagnostics/green_context/qwen_model_probe.py: stock 모델 하네스
- 이전 서비스 trace: ../nsight-diagnostics/README.ko.md

성능 개선 수치는 아직 없다. 기존 Baseline v1을 이 프로파일링 시간으로 덮어쓰지 않는다.
