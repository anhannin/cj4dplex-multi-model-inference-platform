# main 제출용 정리 실행 계획

승인: 사용자가 프롬프트와 검토 수정사항(브랜치 충돌·삭제된HTTP·경로보존·SLO/관측범위)을 승인했다. 원격push/기본branch변경은별도확인한다.

## 시작 상태/보존
- 작업은기존main(5a69e1a)의격리worktree에서수행한다. 새branch생성없음.
- baseline90cb3fa의소스·근거·삭제내역을병합하되,mainREADME원문을먼저보관하고README충돌은main본문유지로해결한다.
- baseline90cb3fa 및frozen-tag6a99fda는변경하지않는다. 원본결과·results/src·baseline스냅샷이동/삭제없음.
- API/FastAPI와일회성wrapper는이미삭제된상태를유지한다. 149개CPU회귀로동작경계를확인한다.

## 범위
1. 원래mainREADME를유지하면서깨진경로/부정확한scope만최소수정한다.
2. 실험6단계별README와EXPERIMENT_INDEX를추가한다. 원시자료는복제하지않고원래경로로연결한다.
3. 기존ARCHITECTURE/TECHNICAL_REPORT/CODE_MAP/REPRO/권리고지를재사용한다. IMPLEMENTATION과DEPLOYMENT_MODES문서를추가하고기본/일반MPS/정적MPS·Queue8vs16/512·현재복원상태를구분한다.
4. Executive Summary와PDF를Burst주평가에맞춰최소보완한다. 이미작성한보고서를영문소문자중복문서로만들지않는다.
5. 생성물/링크/README숫자/manifest정적검사·DockerCOPY·shellsyntax·CPU회귀·실제원시자료사본오프라인재집계를검증한다. 새GPUbuild/추론/배포성공을주장하지않는다.
6. readonly검토후로컬main병합commit만생성한다. 원격push는미실행으로보고한다.

## 소유권
- 실험문서담당: experiments/01~06/README 및docs/EXPERIMENT_INDEX.ko.md만.
- 구현/배포문서담당: docs/IMPLEMENTATION.ko.md와DEPLOYMENT_MODES.ko.md,ARCHITECTURE.ko.md만.
- leader: README정합성·요약본·검증도구/회귀·metadata·최종통합.

## 종료 기준
README에서코드/실험/결과/장애/재현/한계까지모든새링크가열리고,보존source/raw는변경되지않으며,실행검증vs정적검증/미검증이명확하다. 외부권리·수신자접근·실제제출/push는남은항목으로분리한다.
