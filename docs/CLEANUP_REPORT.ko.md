> 아래는첫제출정리기록이다. 이후사용자요청에따른실행파일삭제는[최신정리기록](EXECUTABLE_CLEANUP.ko.md)을따른다. 첫단계162개테스트/README만차이상태와현재142개/승인삭제상태를구분한다.

# 제출용 코드·문서 정리 기록

## 범위와 동작 보존

문제는 측정된 추론 코드의 잘못된 동작이 아니라 **옛 README·여러 실험 단계·대형 원본이 한 저장소에 섞인 탐색성**이었다. 측정 뒤 모델 호출/Queue/Worker를 리팩터링하면 보고서와 실행 소스의 대응을 흐릴 수 있어, runtime 코드를 사후 변경하지 않았다. 코드 지도·최신 진입점·제출 검증/복사 도구로 책임 경계를 정리했다.

- 원래 README는 `history/baseline-root-README.md`로 바이트 보관.
- 동결 `baseline/`와 Git ref, ROS 추론 서버·클라이언트·실험 source/raw는 보존.
- 과거 HTTP/Green/초기 탐색을 삭제하지 않고 최종 경로와 구별.
- 새 runtime 라이브러리·공통 ModelBackend·추론 wrapper·기능 추가 없음.
- Git commit/push, 원격 서비스 설정변경, 새GPU실험 없음.

## 계획·검토 분리

[정리 계획](plans/2026-11-12-submission-cleanup.md)을 먼저 작성하고 독립 read-only 검토를 받았다. 최종 보고서·요약·아키텍처·검증 도구도 별도 검토했다. Git없는payload에대한자동fallback처럼읽히던재현문구를명시적`verify_export.py`분기로수정했다.

## Fallback/중복 분류

| 발견 | 분류·조치 |
|---|---|
| diagnostics의 상대import/복사본이름 호환 | 당시Spark실행묶음을재현하는근거있는compatibility경계. 삭제하지않고CodeMap/재현안내에설명 |
| Slack알림예외를실험실패와독립처리 | 알림장애가실험/복원을중단하지않는fail-open. 본실험오류·복원오류는별도기록/전파됨. 측정소스사후변경안함 |
| 역사적구현의'현재'표현 | 원문보존,root최신진입점에서해당작성시점의상태임을명시 |
| generated node/src중복 | 원시실행증거이므로통합/삭제안함 |
| 대형SQLite/Nsight·사진·compiledbinary | 원본보존,명시적export제외사유/크기/SHA기록. 자동git add/외부upload안함 |
| 문서숫자의수동복사불일치가능성 | JSON기반표생성+provenanceSHA+삽입표일치검사 |

## 변경 파일과 간소화

- `README.md`: 초기탐색·중복안내를최신제출진입점으로대체.
- `TECHNICAL_REPORT.ko.md`, `EXECUTIVE_SUMMARY.ko.*`, `ARCHITECTURE.ko.md`, `architecture.svg`: 제출물완성.
- `REPRODUCIBILITY.ko.md`, `CODE_MAP.ko.md`, `USAGE_AND_LICENSES.ko.md`, `SUBMISSION_CHECKLIST.ko.md`: 실행경계·출처·남은조건문서화.
- `../scripts/render_submission_tables.py`: 원본집계표/수치근거생성.
- `../scripts/check_submission.py`: Git기준선·문서링크·수치·현재텍스트비밀패턴검사.
- `../scripts/export_submission.py`, `verify_export.py`: untracked포함명시적source/docs/evidence복사,Git없는payload해시검사. 원본삭제/overwrite거부.
- `../scripts/render_executive_html.py`: 요약PDF용2개printsection생성.
- `../tests/test_submission.py`: 링크·비밀값비출력·아카이브제외경계3개회귀tests.

## 검증

- 변경전159개→정리후162개CPU unittest PASS. 새도구tests는모듈미존재RED확인후GREEN.
- 변경된제출도구Ruff PASS,compileall PASS,`git diff --check`PASS.
- baseline677개Git객체SHA PASS. **작업트리는README만의도적차이**,workingtree677무변경이라고쓰지않음.
- 최종요약PDF A4 2페이지,각페이지와결론직접확인.
- 원본JSON→생성표/metrics→보고서삽입표일치PASS. Markdownlocal링크PASS.
- 작업트리Gittracked/nonignoredUTF8<=50MiB와로컬Git1commit/504개텍스트blob의비밀패턴검사PASS. ignored/이미지layer/외부binary전체의권리·개인정보보증아님.

검증JSON: [validation-summary](submission/validation-summary.json), [자동검사](submission/verification.json), [Git이력검사](submission/git-history-security.json).

## 남은 위험과 미실행

새PC/GPU의cleanbuild및전체성능재실험은하지않았다. NVIDIA이미지·YOLO/AGPL·개별사진권리,외부GitHub/이미지수신자접근검증과실제제출은남아있다. 타입체커는프로젝트에기설정되지않아추가의존성도입없이compile/unittest/Ruff를사용했다. 이정리가프로덕션가용성이나외부배포허가를증명하지않는다.
