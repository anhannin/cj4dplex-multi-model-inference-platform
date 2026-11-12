# 제출 체크리스트

과제 원문 확인 기준: 2026-11-12. 체크는 확인한 사실만 표시한다. 문서 생성과 외부 제출 완료는 다르다.

## 제출물과 설명 범위

- [x] 과제 원문의 전체 소스·설정, 재현 안내, Architecture Diagram/설계 설명, 기술 보고서, 1~2쪽 핵심 요약, 사용 모델/OSS/API/AI/직접 구현 범위 요구를 확인했다.
- [x] [사용 및 라이선스 고지](USAGE_AND_LICENSES.ko.md)에 모델 식별자·출처·주요 OSS·AI 보조와 구현 경계·미확정 권리를 기록했다.
- [x] 소스 작업트리의 최종 README 및 제출 문서/그림 local link 검사 PASS. 제출 복사본은 manifest와 함께 별도 검사한다.
- [x] 핵심 요약 PDF를 렌더링하여 A4 **2페이지** 및 본문·결론 표시를 확인했다.
- [x] 주요 표를 원본 JSON에서 생성·SHA 연결하고 보고서 삽입표와 일치 검사했다. p95 집계·실패·한계는 별도 검토했다. p99 보장 주장은 하지 않는다.
- [x] Architecture Markdown/Mermaid/SVG와 Queue/Worker/Monitoring·구현/제안 경계를 독립 검토했다.
- [ ] 선택사항인 실행 영상은 제공할 경우 실제 동작·실험 조건을 표시하고 개인정보·권리 미확정 사진·비밀정보를 배제한다. 미제출 자체는 과제상 감점 기준이 아니다.

## 재현 및 검증

- [ ] 최종 제출 revision을 고정하고 변경 파일·테스트·lint·정적검사 결과와 미실행 검증을 기록한다.
- [ ] 깨끗한 환경에서 설치·실행·테스트 절차를 검증하거나 미검증 환경/필수 GPU 제약을 명시한다.
- [ ] Qwen snapshot, YOLO 가중치 해시, 기반 이미지 digest 및 실제 배포 이미지 식별자가 기록과 일치하는지 확인한다.
- [x] 호스트 driver `595.99.02`, PyTorch `2.9.0a0` build CUDA `13.0`, CUDA runtime `13.1` overlay를 구분해 기술했다.
- [x] 성능 수치의 실제 실행 출처를 연결하고 SLO 선정 시점·미달 조건·실측/해석을 구분했다.
- [x] 장애 결과는 GPU유휴 SIGKILL·Kubernetes기본복구로 한정하고 미검증 failover/HA/Queue 보존을 구분했다.

## 권리·보안: 외부 전송 전 필수

- [ ] YOLO/Ultralytics의 AGPL 준수 범위 또는 Enterprise 계약을 검토하고 비공개 제출·이미지 재배포 권한을 확정한다.
- [ ] bus.jpg/zidane.jpg의 개별 재배포 권리를 확인하거나 허가된 입력으로 교체한다.
- [ ] NVIDIA 기반 이미지/런타임 및 전이 OSS의 재배포 조건·LICENSE/NOTICE를 확인한다.
- [ ] 전체 Git 이력·작업 트리·빌드 context·이미지 layer·첨부 아카이브에 API key, 토큰, webhook, 개인정보, 사설 주소/접속정보, 회사 기밀·제3자 비공개 자료가 없는지 검사한다. 발견 시 단순 최신 파일 삭제만으로 이력 노출이 해소된 것으로 판단하지 않는다.
- [ ] 모델 캐시·가중치·샘플 이미지·대용량 백업이 실수로 Git/이미지/첨부에 포함되지 않았는지 검사한다.

## 수신자 접근 및 실제 제출 — 아직 수행 완료로 간주하지 않음

- [ ] GitHub 원격 저장소에 최종 제출 revision을 push한다.
- [ ] 요구된 저장소 공개 범위/비공개 초대 정책에 맞춰 평가자에게 권한을 부여한다.
- [ ] 평가자와 동등한 별도 계정/권한으로 clone 및 문서·원시 결과 접근을 확인한다.
- [ ] 필요한 컨테이너를 허가된 저장소에 push하거나 합법적인 전달 경로를 제공한다.
- [ ] 수신자 권한으로 이미지 pull/아카이브 다운로드와 checksum을 확인한다. 로컬 이미지 ID·백업 파일 존재만으로 완료 처리하지 않는다.
- [ ] 제출 링크·브랜치/commit·실행 명령·모델 취득 경로·접근권한·알려진 제한을 최종 전달문에 기재한다.
- [ ] 회사가 안내한 채용 제출 채널로 실제 전달하고 수신/접근 확인을 남긴다.

외부 push·권한 변경·최종 제출은 이 문서 작성만으로 실행되지 않았다. 권리·보안 미확정 항목을 통과한 것으로 표시하지 않는다.


## 이번 정리 작업의 검증 기록

- [x] 실행파일정리후143개 CPU unittest(HTTP전용24개제거,정리경계5개추가) PASS, 변경된 제출 도구 Ruff PASS, compileall PASS.
- [x] baseline Git ref 고정값 및 원본677파일 Git객체 SHA PASS. 작업트리README·개발설정변경/승인삭제는manifest로구분하고원문보관. 측정된 추론 소스/원시자료 변경 없음.
- [x] `docs/submission/verification.json`의 작업트리 UTF8 텍스트<=50MiB 서명검사 및 local link/결과표 검사 PASS. 토큰 값은 출력하지 않는다.
- [x] `docs/submission/git-history-security.json`: 로컬1commit/504개 텍스트blob의 서명검사 PASS. 이는 이미지 layer/외부파일/모든 개인정보의 부재를 보증하는 검사가 아니다.
- [x] 기술문서·수치·아키텍처 독립 검토. Git없는payload검사는별도`verify_export.py`로 안내하도록 수정.
- [ ] 최종 Git commit/push 및 수신자 접근검증은 수행하지 않았다. export manifest는파일묶음검증이며원격revision고정의대체증거가아니다.

세부검증: [validation-summary.json](submission/validation-summary.json), [자동검사](submission/verification.json). 외부제출·권리·새GPU환경 검증이남은것과로컬문서·CPU검증완료를구분한다.
