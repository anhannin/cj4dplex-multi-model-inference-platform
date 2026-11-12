# main 제출용 레포 최종 정리 결과

## 1. 작업 브랜치와 통합

기존 main `5a69e1a`의 README를 먼저 보관하고 baseline `90cb3fa`의 최신 코드·삭제내역·근거를 통합했다. README 충돌은 main 원문을 보존한 뒤 실제 경로/역할/범위 오류만 수정해 해결했다. 새 작업브랜치·기본브랜치 변경·강제push는 없다. baseline 및 동결 태그는 수정하지 않는다.

## 2. 최종 탐색 구조

```text
README.md
ros2/ · clients/                  실제 독립 모델 서비스/UUID 요청
containers/ · k8s/               기존 빌드/배포 경로 그대로
benchmark/ · diagnostics/        기준선·병목·SM·정적MPS·장애·분석 본체
optimization/                   과거 최적화와 재사용 helper
experiments/01_baseline/README.md
experiments/02_bottleneck_analysis/README.md
experiments/03_sm_sensitivity/README.md
experiments/04_hypothesis_validation/README.md
experiments/05_static_mps_optimization/README.md
experiments/06_fault_recovery/README.md
results/ · baseline/             원본 경로·원시자료·당시 실행source 보존
docs/                            기존보고서/구성도/재현·권리문서 재사용
docs/figures/                    기존그래프 유지
scripts/ · tests/                검증·문서생성·회귀
```

가상 src/common이나 빈 deploy폴더를 만들지 않았다. 물리 파일 이동·원시결과 복제 대신 실험README가 코드와근거에 연결된다.

## 3. 새로 작성한 문서·검증

- experiments/01~06/README.md: 목적·가설·환경·부하·조건·절차·지표·결과·분석·한계·아티팩트11항목.
- [실험 인덱스](EXPERIMENT_INDEX.ko.md): 읽는순서와의사결정·실제근거 연결.
- [구현 범위](IMPLEMENTATION.ko.md): 구현/관측/제안 구분.
- [배포 모드](DEPLOYMENT_MODES.ko.md): NoMPS/일반/정적·기본Queue8/실험16·512·복원상태 구분.
- [파일 분류](submission/file-classification.json): 역할별분류이며삭제승인이아님.
- tests/test_main_delivery.py: 새탐색경로·문서11항목·README구조/링크/수치·DockerCOPY·K8s참조·Burst요약회귀6개.

## 4. 수정·재사용·이동

mainREADME는9개기존절·핵심설명·성능표를유지했다. 깨진그림경로,없는serving/mps/figures폴더설명,동결원본식별,다른연구미수행처럼읽히는표현만고쳤다. 문서링크를추가했으며기술보고서/구성도를소문자중복파일로만들지않았다.

기존ARCHITECTURE/REPRO문서를최소보완했고ExecutiveSummary와2쪽PDF를Burst주평가에맞췄다. 실제수행한기타연구자료는본문밖보관인덱스에남겼다. 모델노드·클라이언트·Dockerfile·K8smanifest·계측본체·raw는변경하거나이동하지않았다. 제거된HTTP·일회성실행기를복원하지않았다.

## 5. Baseline 실행·재현

초기580/CUDART13.0의5조건정상측정과최종595/CUDART13.1 Burst대조군을구분한다. 동결원본은브랜치명이아닌태그 `baseline-frozen-20261103`/commit `6a99fda`로식별한다. 자세한호스트준비·원본이미지·권한·복원경계는[재현안내](REPRODUCIBILITY.ko.md)와[배포모드](DEPLOYMENT_MODES.ko.md)를따른다.

## 6. 최적화 실행·재현

nativeMPS실험본체는diagnostics/mps_static/eval_runner.py다. 실제호스트src별칭묶음/원본template·backup/workload와Runtime13.1 overlay가필요하다. Git만clone해파일하나실행하면GPU35회가재현되는제품으로설명하지않는다. 기존raw재집계는임시사본에서수행해원본을보존한다.

## 7. 실험 근거 연결

[01기준선](../experiments/01_baseline/README.md)→[02병목](../experiments/02_bottleneck_analysis/README.md)→[03SM](../experiments/03_sm_sensitivity/README.md)→[04가설](../experiments/04_hypothesis_validation/README.md)→[05정적분할](../experiments/05_static_mps_optimization/README.md)→[06장애](../experiments/06_fault_recovery/README.md)를읽는다. 큰SQLite/nsys바이너리는의도적로컬제외이며제출된CSV/JSON·hashmanifest와구분한다.

## 8. 실제 검증 결과

- CPU155테스트PASS. 새6개문서·정적경계테스트는기능의GPU실행을증명하는것이아니다.
- DockerCOPY경로,주요manifestvolume/GPU참조,JSON7파일·YAML7문서파싱PASS. 클러스터API호출/배포없음.
- Bash문법·compileall·변경PythonRuff·문서상대링크·README수치대조PASS.
- baselineGit객체677개와보존source145개검사PASS. core/raw폴더의baseline90대비diff없음.
- 원본사본재집계: static감사12,005응답(워밍업포함),별도보관연구55,620응답/40회,fault28응답/복원PASS. 이재집계는새측정이아니다.
- ExecutivePDF A4 2페이지,결론/푸터확인. 기존TechnicalPDF11페이지유지.
- 독립검토에중대한오류없음. 검증JSON은[MAIN_VALIDATION](submission/MAIN_VALIDATION.json)을따른다.

## 9. 수행하지 않은 검증

새GPU추론·드라이버설치·모델이미지cleanbuild·Kubernetesapply·실제장애주입은이번정리에서수행하지않았다. 과거관측과이번정적/CPU검증을구분한다. 8/40영구운영배포나자체HA를구현했다고하지않는다.

## 10. 제출 전 남은 확인

main의로컬정리가끝나도원격push는별도사용자확인이필요하다. 평가자계정의clone/이미지접근,YOLO/AGPL·NVIDIA조건·샘플사진개별권리,실제채용제출은[체크리스트](SUBMISSION_CHECKLIST.ko.md)의별도항목이다. git기본branch변경이나공개범위변경을임의로하지않는다.
