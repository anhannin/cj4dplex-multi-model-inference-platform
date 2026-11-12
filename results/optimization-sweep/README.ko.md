# DGX Spark 두 모델 최적화 비교 결과

측정일: 2026-11-04(KST). **현재 시험 조건에서의 추천은 MPS(Qwen 활성 스레드 한도50%, YOLO100%) + YOLO TensorRT + DDS 초기 타이머 조정**이다. 모델별 독립 FIFO/Worker, 두 Pod 및 UUID별 결과 채널은 유지했다. 기술을 영구 확정한 것이 아니라 검증한 후보를 추천하며, 서버는 원본 baseline으로 복구했다.

## 1. 최종 재측정: 최적화 없는 동시 실행과 비교

원본 조건 Qwen30회(연속된10회+20회 두 측정 창), 추천 조건30회. 각 창 워밍업5회 제외. 같은5개 프롬프트, 생성128토큰, Qwen BF16/SDPA/기존 커널, 같은 두 이미지/YOLO26l640×640/batch1, 모델당 동시 요청1개(C1). YOLO는 Qwen 종료까지 반복한다. 아래 감소율은 과거 v1 단독 실행이 아니라 **같은 날 새로 측정한 동시 실행 control** 기준이다.

| 지표 | 최적화 없음 | 추천 조합 | 변화 |
|---|---:|---:|---:|
| Qwen 평균 E2E(s) | 16.13 | 13.33 | 17.4% 감소 |
| Qwen p95 E2E(s) | 16.48 | 13.37 | 18.9% 감소 |
| Qwen 서버 TTFT 평균(ms) | 131.69 | 106.83 | 18.9% 감소 |
| Qwen TPOT 평균(ms/token) | 125.89 | 104.07 | 17.3% 감소 |
| YOLO 평균 E2E(ms) | 39.74 | 23.62 | 40.6% 감소 |
| YOLO p95 E2E(ms) | 48.59 | 32.69 | 32.7% 감소 |
| YOLO 프레임워크 inference 평균(ms) | 16.78 | 8.43 | 49.8% 감소 |
| YOLO 처리량(요청/s) | 24.37 | 40.24 | 65.1% 증가 |
| 측정 실패(Qwen / YOLO) | 0 / 0 | 0 / 0 | 관측된 실패 없음 |
| 측정 요청 수(Qwen / YOLO) | 30 / 11793 | 30 / 16089 | 실제 요청 수 공개 |

- 원본: `confirm-a-control`, `confirm-a2-control`; 추천: `confirm-b-trt-dds-mps-q50`.
- [합산 control](analysis/control-pooled.json), [추천 결과](analysis/winner.json), [수치/계산식 입력](analysis/final-metrics.json), [전체 run CSV](comparison.csv).
- 처리량은 각 측정 창의 시간 합으로 계산했고 p95는 원시 요청을 합친 뒤 다시 계산했다. 평균 p95를 사용하지 않았다.
- TTFT는 서버 내부 첫 토큰 시점이다. 현재 ROS 응답은 완성된 텍스트 한 번이므로 클라이언트 스트리밍 TTFT가 아니다. YOLO inference는 Ultralytics 동기화된 host 측 단계이며 순수 GPU kernel 시간과 동일하지 않다. 중첩된 timing을 중복 합산하지 않았다.

## 2. 개별 방법 및 조합 탐색

각 행 Qwen 측정5회, 워밍업5회. YOLO 요청 수는 조건별 달라진다. 작은 N의 p95는 탐색용이다. 주요 세 축(MPS50 / TensorRT / DDS)의8개 조합을 모두 실측했고, 다른 MPS 제한 비율과 CPU 분리도 비교했다.

| 조건 | Qwen 평균 E2E(s) | YOLO 평균(ms) | YOLO p95(ms) | YOLO 요청/s |
|---|---:|---:|---:|---:|
| 최적화 없음 | 16.029 | 39.78 | 48.89 | 24.28 |
| MPS 무제한 | 12.803 | 61.29 | 72.69 | 15.96 |
| MPS Qwen75 / CV100 | 13.769 | 39.47 | 48.71 | 24.50 |
| MPS Qwen50 / CV100 | 13.667 | 30.91 | 39.24 | 30.97 |
| 빠른 CPU 코어 분리 | 15.865 | 40.96 | 115.02 | 23.61 |
| DDS 초기 타이머 | 16.442 | 37.48 | 47.83 | 25.80 |
| YOLO TensorRT | 14.098 | 35.19 | 47.86 | 27.36 |
| TensorRT + DDS | 14.307 | 33.01 | 44.75 | 29.08 |
| MPS50 + DDS | 13.741 | 29.59 | 39.52 | 32.34 |
| MPS50 + TensorRT | 13.306 | 25.88 | 38.73 | 36.77 |
| MPS50 + TensorRT + DDS | 13.317 | 23.29 | 34.78 | 40.70 |

판단:
- **MPS 무제한**: Qwen은 빨라지지만 CV 지연·처리량이 악화됐다. 무조건 켜는 방식은 제외한다.
- **MPS50**: 두 지표의 균형이 좋았다. 한도는 고정 SM 독점 할당이나 메모리 격리가 아니다. 별도 CUDA client에서 유효 SM 수가50%→24/48로 바뀌는 것을 확인했고, 실제 두 Pod의 MPS client 연결 PID를 보관했다.
- **CPU affinity**: Qwen5–9 / YOLO15–19(실제 빠른 코어3900MHz) 분리. 이 조건에서는 뚜렷한 이점이 없고 CV 꼬리 지연이 커져 채택하지 않았다. 다른 부하에서도 항상 나쁘다는 결론은 아니다.
- **TensorRT**: 원래 모델/공식 `YOLO.predict()`를 유지했다. compiler/backend 최적화가 유효했고, MPS/DDS에 추가해도 이득이 남았다.
- **DDS**: per-request endpoint의 초기 reliable handshake 지연을 줄이는 방향. ACK를 없애거나 결과 publisher를 일찍 파괴하지 않았다. 서버뿐 아니라 **요청 클라이언트에도** XML을 적용했다.
- 관리 단순성이 더 중요하면 **TensorRT+DDS(MPS 없음)**, backend 정밀도 정책을 바꾸지 않으려면 **MPS50+DDS(TensorRT 없음)**가 대안이다. 표의 실제 성능 손실과 비교해 선택한다.

## 3. 전송 지연 가설 검증

모델 둘을 상주시킨 채 YOLO만 요청,500회씩 control→DDS→control→DDS 반복:

| 순서 | 평균 E2E(ms) | p95(ms) | 응답 ACK p95(ms) |
|---|---:|---:|---:|
| control1 | 25.59 | 96.61 | 83.37 |
| DDS1 | 18.94 | 26.42 | 12.88 |
| control2 | 26.89 | 97.20 | 83.56 |
| DDS2 | 18.59 | 26.56 | 12.62 |

각 run500/500 publication 로그가 연결됐고 ACK 실패는0이다. 두 초기 타이머를 함께 변경한 실험으로, 어느 한 타이머의 단독 기여를 분리한 것은 아니다. GPU 최적화 없이도 운영 지연이 개선됨을 확인했다. [FastDDS2.14.7 타이머 정의](https://fast-dds.docs.eprosima.com/en/2.14.x/fastdds/dds_layer/core/policy/eprosimaExtensions.html), [설정 및 버전 근거](../../optimization/SOURCES.md).

## 4. 빨라진 CV의 부하 증가를 구분한 보조 실험

주 시험은 adaptive closed-loop이므로 추천 조건이 더 많은 CV 요청을 처리한다. 별도로 양쪽 client에 CV launch 상한20/s를 적용했다. **고정 open-loop 도착률이 아니며 실제 처리율도 완전히 같지 않다.**

| 조건 | Qwen N | Qwen 평균(s) | YOLO 평균(ms) | YOLO p95(ms) | 실제 CV 요청/s |
|---|---:|---:|---:|---:|---:|
| control, 상한20/s | 10 | 14.864 | 39.54 | 48.28 | 18.67 |
| 추천, 상한20/s | 10 | 12.735 | 24.72 | 31.08 | 19.46 |

작은 표본의 보조 확인이며 완벽한 동일 offered-load 격리 실험으로 주장하지 않는다. 같은 상한에서도 개선 방향이 유지됐다.

## 5. 기능·정밀도·운영 비용

- Qwen은 원본9B BF16, 모든 측정 요청 출력128토큰. 입력 hash/모델 설정/UUID를 감사했다. greedy여도 Pod 재시작 뒤 출력 문자열이 달라지는 경우가 있어, 의미 품질이나 byte-exact 출력을 보장한다고 주장하지 않는다.
- TensorRT10.13.3.9, Ultralytics8.4.198의 원본 exporter, `quantize=16`, 고정640/batch1, workspace2GiB, simplify=False. **FP16 tactic 허용 engine이며 입력/출력 binding은 FP32**다. 전 계층·I/O가 순수 FP16이라는 뜻이 아니고 원본 PyTorch FP16과 정밀도 정책 차이를 공개한다.
- 이미지2장: 검출 개수 bus5 / zidane3 및 클래스 일치, 최소 matched IoU **0.997625**, 최대 confidence 차이 **0.000977**. [원시 fidelity 결과](20261104-v1/results/trt-quality.json). 이는 COCO mAP/전체 정확도 검증이 아니다.
- TensorRT export19.4초, engine55,155,153bytes(SHA256 `6970da6de78d151df9c0c2b51e0dd9da87748793a88974ee18da159c9eb6b54f`). 장비/runtime 변경 시 재빌드·재검증이 필요하다. engine은 로컬 `/home/avees/cj-optimization-artifacts/20261104-v1/yolo26l.engine`에 별도 보관했다(Git 제외).
- MPS daemon 관리 및 공유 장애 영향, TensorRT 품질/장비 호환성 검증이 추가 운영 비용이다. 아직 daemon 상시 supervision/장애 복구까지 구현한 production 배포라고 주장하지 않는다.
- GB10 unified memory에서 NVML VRAM 총량/사용량이 N/A이므로 VRAM 절감·전력 효율 개선은 결론내리지 않는다.

## 6. Green Context / MIG 판단

- 기존 Green 기능 probe는 실제 모델의 선택 stream 연결을 확인했다. 별도 프로세스의 합성 fixed-work는 MPS 없이 직렬화에 가까웠고, MPS+Green에서는 약191ms로 동시 진행(단독 시간 합 약382ms)을 확인했다.
- 그러나 MPS+Green의 각 client에서 관찰한 SM-ID 공간은16개(0–15),32개(0–31)로 겹쳤다. client 간 물리 SM-ID namespace가 같은지도 검증하지 않았다. **동시 진행은 확인했지만 전역 물리 SM 독점 분할이나 MPS 대비 Green 추가 이득을 입증한 것은 아니다.** 실제 Green serving 성능 비교로 포함하지 않는다.
- [합성 concurrency](20261104-v1/results/green-mps-concurrency/summary.json), [mapping](20261104-v1/results/green-mps-mapping/summary.json), [CUDA13의 동시 진행 보장 관련 주의](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-driver-api/group__CUDA__GREEN__CONTEXTS.html).
- 현재 장비/driver에서 MIG는 N/A로 보고돼 적용하지 않았다. 단일 프로세스 통합이나 driver/전역 설정 변경으로 우회하지 않았다.

## 7. 실패와 증거 보존 한계

1. 초기 TensorRT 자체 exporter/추론은 성공했으나, 후보 node의 시작 검증이 예전 `.engine` 속성을 참조해 startup에 실패했다. 설치된 SDK의 `.format == 'engine'`으로 수정하고 회귀 테스트한 뒤 측정했다. [초기 실패 원문](20261104-v1/results/trt-startup-v1-failed.log), [실패 소스](20261104-v1/src/versions/trt-v1/yolo_trt_node.py). 이 장애를 숨기거나 정상 측정 요청 실패0과 혼동하지 않는다. framework 원본은 수정하지 않았다.
2. 긴 run 종료 후 `kubectl logs`만 수집한 탓에 log rotation 이전의 후행 ACK 로그 일부가 누락됐다. `confirm-a2` CV4020/8015, `confirm-b` CV131/16089만 publication 연결 가능하다. **원시 client의 모든 E2E/response 내 inference·queue timing은 보존됐다.** 누락 ACK를0으로 채우지 않았으며 주 비교의 완전한 ACK 분해를 주장하지 않는다. 기존 Pod 로그 경로는 삭제돼 복구할 수 없었다. [감사 결과](analysis/protocol-audit.json), [Kubernetes 로그 회전 제약](https://kubernetes.io/docs/concepts/cluster-administration/logging/).
3. 후속 실험용 수집기를 사전 live-follow 방식으로 보완했다. 별도 원본 CV5000회에서 **publication5000/5000·ACK 실패0**을 수집했고, 같은 시점의 종료 후 snapshot에는0/5000만 남아 회전/retention 손실을 재확인했다. [검증 JSON](20261104-v1/verification/live-log-rotation-check.json). 이는 해당 검증 run의 완전성 확인이며 모든 미래 회전 조건의 보장은 아니다. 매 run UUID coverage 검사를 유지한다. 검증 결과를 전후 성능 비교에 섞거나 과거 누락을 복구했다고 주장하지 않는다.

## 8. 보존·복구·재현

- AI Coding Assistant가 실험 스크립트·설정·실행·분석 문서 작성을 지원했다. 결과 수치는 실제 Spark 측정 파일에서 계산했고 공개 framework 추론 구현 자체는 수정하지 않았다.
- [실험 소스와 명령](../../optimization/README.md), [사전 계획/평가 계약](../../docs/plans/2026-11-04-optimization-sweep.md).
- 당시 서버 코드·설정·원본 template 백업·raw requests·가용 서버 로그·검증 기록: `20261104-v1/`. 해당 archive의 `ARTIFACTS_SHA256SUMS`로 전송 무결성을 확인한다. 초기 수집기 소스도 `src/versions/pre-live-capture/`에 보존했다.
- 양쪽 live `spec.template`은 원본 백업과 정확히 일치, replicas1씩 복원. private MPS controller는 연결 client가 없는 것을 확인한 뒤 종료. 원본 모델 실제 E2E 요청도 성공했다. [복구 검사](20261104-v1/verification/restored-templates.json), [MPS 종료](20261104-v1/verification/mps-cleanup.log), [복구 후 health](20261104-v1/verification/health-final.log).
- 동결 baseline의**677개 checksum 재검증 PASS**, **107개 단위 테스트 PASS**, 변경 코드 Ruff/compile 검사 PASS. [검증 기록](verification/). 총21개 run의62,610개 요청(워밍업 포함)에서 UUID·응답 상태·해당 입력/토큰 계약 감사가 PASS였다(후행 ACK 로그 coverage의 위 한계는 별도 공개). baseline source/이미지/weights/클러스터 GPU-sharing 정책은 변경하지 않았다. 수정/추가 코드는 `optimization/` 및 별도 후보 node이며, inference/queue/publication 본문은 원본과 동일하다.

## 9. 적용 전 남은 검증

현재 고정 corpus·짧은 프롬프트·128토큰·C1/model·서버 로컬 client의 결과다. 모든 조건의 전역 최적해, 사업 SLO 충족 또는 고가용성을 뜻하지 않는다. 실제 SLO와 traffic mix를 정한 뒤 긴 prompt/출력, 다른 이미지, open-loop 및 높은 동시성, 최적화 상태의 단독 실행, 장시간 안정성, 모델 정확도, MPS 장애 복구를 추가 검증해야 한다. 기존 per-user linger 운영 수정 이후 새 control을 사용했으며 과거 v1 수치와 직접 합산하지 않았다.
