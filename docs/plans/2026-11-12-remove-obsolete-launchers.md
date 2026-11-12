# 불필요 실행 경로 제거 계획

사용자 승인: 테스트 중 만든 불필요 실행파일을 삭제하되 baseline부터 최적화 과정 재현용은 남긴다.

## Behavior lock / scope
- 변경 전 전체162개 unittest PASS와 baseline Git ref/ROS노드/clients/benchmark/진단source 해시 기록.
- 실제선택ROS2/Kubernetes, Docker모델기반worker, 5조건baseline, 과거최적화본체,SMsweep,Green검증/helper, nativeMPSstatic, 지속부하, 유휴장애, GPU진단/분석은유지.
- 삭제: HTTP서빙전체/HTTP클라이언트/전용Dockerfile·실행기·테스트·의존성; 초기cj-preflight launcher와run_preflight; sleep개발컨테이너launcher; 이미끝난실험의PID대기·Slackwatch·로컬수집일회성wrapper.
- baseline/ 및 results/ 전체(당시source사본포함)는변경/삭제하지않는다. 런타임server/측정로직변경없음. 서버접속/배포/새GPU실험없음.
- 삭제대상은저장소밖백업과SHA목록을먼저작성해복구가능하게한다. 삭제는작업트리의활성코드에서실제로제거하며archive/로이름만바꿔남기지않는다.

## 의존성 확인/분류
- HTTP코드는최종ROS/진단에서import안함. HTTPtests4개만같이삭제하고 HTTP전용dev의존성제거.
- `worker.py`는두모델Dockerfile ENTRYPOINT,가속검사와모델이미지검증기는남김.
- native정적분할이 `green_burst.generate`→`green_e2e.generate`,MPSrunner/runtime,optimization/live_logs를참조하므로이전helper를삭제하지않음. fallbackimport는Spark당시별칭묶음의근거있는compatibility경계라유지.
- PID기다리기/shutdown뒤export·collectwrapper는실험연산·입력·스케줄·분석본체가아님. 해당기능은본체명령직접실행으로대체,이미그려진결과는보존.

## 검증
1. 삭제목록·보존핵심경로 regression test RED→GREEN.
2. `.dockerignore`,requirements-dev,최신코드맵/README/재현안내를정리된tree에맞춤. 오래된문서는역사문서주의명시.
3. baseline검사기는원본Git객체677을계속검증. 작업트리의승인삭제/변경을SHA기반cleanup-manifest와대조하며무관한변경을묵인하지않음.
4. 살아있는tests전체/compile/shell문법/제출검사;3최종실험은원본사본에서오프라인재집계.
5. 새제출export(v3)만생성해hash·CPUtests검증.구v2와원본실험은보존.
