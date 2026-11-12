# 지속 동시 부하 실험 실행 계획

**목표:** 동일 지속 부하에서 MPS 없음 대비 Qwen 전체응답 E2E p95 증가 0% 이하와 YOLO E2E p95 20% 이상 감소를 동시에 만족하는지 독립 검증한다.
**구조:** 기존 immutable 이미지/추론 계측 코드는 그대로 복사한다. Qwen C1 closed-loop, YOLO 일정 간격 open-loop. 개별 UUID 응답 채널 및 독립 FIFO 유지. 현재 운영 템플릿/replica/MPS 상태 백업 후 finally 복구 및 실제 응답 확인.

## 통제 및 판정 사전 고정
- 기존 Burst와 통계 혼합 금지. Green 없음, actual CUDART13.1, driver595.99.02, Qwen512input/128output, 동일 bus640 YOLO/b1, CPU4threads.
- 4설정: control / mps-only / static-q8-y40 / static-q16-y32.
- 예비 control 30초×요청률8,15,22,30 req/s (같은 설정 내 워밍업 후 단계별 완전 drain). 안정성은 후반 server Queue 대기 평균<=100ms, 후반 Queue 증가기울기<=0.1 request/s, 에러0. 안정 최대율보다 낮은 안정율 하나와 안정 최대율을 선택. 안정값이 2개 미만이면 낮은 값 추가탐색. 30도 안정이면 높은 값 추가탐색. 최종률/근거를 본실험 전에 파일로 고정.
- 본실험 120초 요청생성, 4설정×2요청률×5round=40회. round별4설정 무작위, 각 설정 내2요청률도 무작위. 각 trial 새 Pod/워밍업3Q30Y; 부하 시작 공동 t0. Qwen C1은 응답 후 즉시 다음 요청(새 요청은120초전까지만), YOLO는 t0+i/rate의 고정스케줄. 종료후300초 drain, 미완료 timeout 기록하고 run FAIL. 부하 생성기 지연도 저장하며 p95>10ms 또는 max>100ms이면 generator-validity FAIL, 성능결론에 사용하지 않음.
- Qwen은 응답속도에 따라 표본수 달라짐. 한 run 약10개 수준 p95 한계 공개. 주판정은 각 trial p95의 5회 평균을 같은 요청률 control에 비교. pooled p95는 보조, 반복별 값/범위 및 paired 변화율도 공개. 0% 관측통과는 통계적 동등성 증명 아님.
- E2E: JSON직렬화/publish 직전→결과JSON파싱 완료. scheduled→결과도 보조 기록하여 발행지연 은폐 방지. CUDAevent는 GPUforward 경과구간이지 순수SM실행시간 아님.
- 모든 발행/오류/timeout 보존. 요청생성120초까지만 응답한 것만 선택하는 censoring 금지. drain동안Qwen이 먼저끝난 후YOLO잔여는 분리 가능하도록 timestamp보존.
- 예비/본실험 단계별 raw/log/metadata 보존. 지속적인 request 공급이 GPU100%점유를 보장하지 않음.

## 실행 작업
1. scheduler/선택규칙 tests RED→GREEN, 기존152tests 보존.
2. 기존 계측 node 복사/hash, 별도 sustained client/controller 추가; smoke 10초와 raw audit.
3. preflight/백업/lock, pilot→rates.json 확정→40본측정. host1Hz 관측, livePodlogs, membership pre/post. 오류는 중단/복원/Slack.
4. raw 전송 및 SHA검증, 독립 통계/그래프, SLO 결과와 한계 한국어 보고서.
5. 기존 baseline MANIFEST SHA 재검증, 운영상태/template/replica/서비스 및 실제 ROS응답 복구 확인.

**중단조건:** GPU/노드 이상, 외부실험충돌, timeout/overflow/요청누락, 잘못된runtime/SM/모델입력, 부하 생성기 허용지연 위반. 실험 실패는 로그보존하고 원인수정 후 새 label로 재시도하며 실패기록 삭제하지 않음.

## v2 사전 수정 — 2026-11-11 16:35 KST
v1 일반MPS/15req/s에서 모든 요청 정상응답이었지만 발행지연p95=20.247ms로 gate10ms를 초과했다. 주성능자료에서 v1전체를 제외하고 원본과 복원을 보존한다. 후반 pending UUID reader 증가와 함께 발행지연이 증가했고 publish 자체 p95는 약1.8ms로 유지되어, Python callback/구독 관리와 같은GIL을 공유하는 발행 thread 간섭을 제거한다.

- YOLO 발행기를 spawn한 별도 ROS publisher 프로세스로 분리. 공유메모리로 실제 sent/publish-return timestamp를 전달. Qwen C1과 결과 구독은 기존 client process 유지.
- future CLOCK_MONOTONIC t0를 공유하여 동시에 시작. UUID/result topology, inference source, payload, QoS, queue, SLO, validity threshold는 유지.
- v1 유효 control-only pilot에서 선택한8/15req/s 고정. v2 control30s15req/s + 문제조건 일반MPS120s15req/s로 generator 검증 후, 모든40회 새로 실행한다. v1의 유효5회도 재사용하지 않는다.
- v1은 results/sustained/20261111-v1에 실패기록으로 별도 보관. v2가 최종 본측정.
