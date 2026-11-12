# 제출용 코드·문서 정리 계획

**Goal:** 측정 동작과 원본을 바꾸지 않고 PDF의 제출물 여섯 항목을 정확한 한국어 문서·검증 가능한 저장소 진입점으로 완성한다.
**Architecture:** 기존 ROS2 노드/클라이언트/실험계측 코드는 보존한다. README는 최신 제출 진입점으로 교체하고 이전 README 바이트는 docs/history에 보관한다. 최종 보고서/요약/구성도/재현/사용내역을 연결하고 표 수치는 검증된 raw 집계에서 생성·대조한다.
**Tech Stack:** 기존 Python unittest/Ruff, Markdown/Mermaid, 표준라이브러리 기반 오프라인 제출 검증. 새 런타임 의존성 없음.

## 승인된 범위와 제약
- 사용자는 직전 논의한 필수 문서/재현/비밀정보 점검과 필요한 코드 정리를 자율 완성하도록 요청했다. 새 아키텍처나 추론 기능을 추가하지 않는다.
- GPU 실험 재수행/서버배포 변경/외부공개/commit/push/기존 결과삭제 금지.
- baseline Git ref 6a99fdaf26307e2f0b41f708478fdec3fcfad7ac 및 baseline/ 원본 보존. 현재 README는 baseline manifest에 포함되므로 **진입점 수정 후 working-tree677개 일치라고 주장하지 않음**. git baseline의 원본677개를 object로 검증하고 README 변경은 명시한다.
- Burst를 주요 시나리오로 설명하되 결과기반 범위정리·SLO선정 시점을 숨기지 않는다. 지속부하 미달조건·TTFT 비용·YOLO GPUevent 악화도 공개한다.
- MPS static8/40은 추천후보이며 실제운영은 원복된normalMPS+Green16/32. 재배포했다고쓰지 않는다.

## 변경 전 behavior lock / inventory
1. 전체 기존159 unittest 실행, 기존baseline workingtreeSHA677와gitref를 기록한다.
2. 명확한 stale 문서: rootREADME의 '현재branchbaseline/미완성API/초기탐색' 표기는 역사문서로 이동.
3. diagnostics의 source-copy/import-path compatibility는 Spark historical src bundle을 재현하는 근거 있는 compatibility 경계. 삭제/통합하지 않고 코드맵에 설명한다.
4. Slack alert 예외무시는 실험실패를 알림장애로 가리지 않기 위한 fail-open. 본실험 exception/restorationFAIL은 전파됨. 바꾸지 않는다.
5. FastAPI/초기탐색/Green 실패자료는 측정 이력으로 유지하고 현재선택과 구분. 새runtime공통wrapper/모델추상화 추가하지 않음.

## 작업과 검증
- A: baseline 원본README 보관, 증거목록·정리검증 JSON 저장(비밀값/원본운영credential 제외).
- B: docs/TECHNICAL_REPORT.ko.md, EXECUTIVE_SUMMARY.ko.md(1~2p출력), ARCHITECTURE.ko.md+Mermaid 작성. 핵심 숫자는 static/sustained/fault JSON 근거링크와 교차검증.
- C(독립): docs/REPRODUCIBILITY.ko.md, CODE_MAP.ko.md를 현재파일·명령과 대조해 작성. CUDART13.1overlay와host경로/이미지접근제약 공개.
- D(독립): docs/USAGE_AND_LICENSES.ko.md, SUBMISSION_CHECKLIST.ko.md. 모델/OSS/데이터 권리 official-source 검증, 미해결은미해결로 남김.
- E: 제출검증 script/tests를 RED→GREEN으로 추가: Markdown local링크/제출물존재/주표수치/비밀패턴/대형파일·ignoredraw·baseline gitobject검증. 비밀값 출력금지; 탐지결과는 경로/유형만.
- F: 최신README 단일진입점, 역사자료경고/폴더지도. 부정확한 '현재' 문서는 변경대신 최신문서우선범위를안내한다.
- G: writer와별도reviewer로 계획/최종문서검토. 전체tests/Ruff/compile/링크·baseline·수치·보안·산출물사이즈검증. GPU경로는새실행하지않았다고명시.

## Stop condition
필수제출문서·구성도·요약·테스트가능한실행안내가 있고, 검사통과/실행불가범위/외부접근·라이선스결정대기항목이 구분되면 종료한다. 새기능·실험·공개로범위를확장하지않는다.
