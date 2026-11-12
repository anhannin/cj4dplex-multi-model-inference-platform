# 활성 실행파일 정리 결과 — 2026-11-12

## 제거 범위

총38개파일을활성작업트리에서제거했다. 파일별SHA와사유는[cleanup-removals.json](submission/cleanup-removals.json)에기록했다.

- 미선택HTTP스택: `api/`, `serving/`, `clients/http/`, HTTP전용Dockerfile4개, build/start/smoke실행기4개, HTTP회귀파일4개, HTTP의존성파일.
- 초기환경탐색: `scripts/launch_remote.sh`, `scripts/run_preflight.py`, `containers/start-dev.sh`.
- 일회성대기/수집: optimization의종료대기shell5개,watch_sweep,benchmark/watch_run,sustained/collect_when_done.
- 중복다운로드: 이전코드zip3개. 사진·실측자료는여기서삭제하지않음.

재현에필요한Docker환경/볼륨/컨트롤측정호출은[직접실행명령](REPRO_COMMANDS.ko.md)에보존했다. source삭제전백업은저장소밖`/home/avees/cj-cleanup-backup/20261112-obsolete-v1`에있고제출활성코드에는포함하지않는다.

## 보존 범위

- 실제ROS2노드2개/UUID클라이언트2개와그동작은변경하지않음.
- 모델DockerfileENTRYPOINT인`worker.py`,가속·설치검사·모델컨테이너검증기를보존.
- 5조건baseline·과거최적화본체·SMsweep·Green검증·nativeMPS정적분할·지속부하·장애·병렬성진단/집계보존.
- 최종MPS정적분할이재사용하는`green_burst`→`green_e2e`generator,MPSruntime/runner,`optimization/live_logs.py`를보존.
- `baseline/`와`results/`는당시실행소스사본까지그대로보존. 이스냅샷안에옛HTTP/일회성파일이남는것은증거보존이며활성실행경로가아님.

## 회귀·안전 검증

- 정리전162개CPU회귀통과. HTTP대상제거로전용24개를함께제거하고정리경계5개를추가하여정리후143개통과.
- 새5개는삭제전RED확인후GREEN. 최종필수파일존재,제거경로부재,HTTPimport의존없음,승인SHA와다른변경거부검사.
- 보존하는ROS/clients/benchmark/diagnostics/optimization145개파일은삭제전후SHA동일을검사한다.
- baseline677개Git객체는여전히검증한다. workingtree삭제/개발설정변경은정확한경로와SHA로승인기록과대조하고무관한runtime변경은실패처리한다.
- 서버배포/이미지/새GPU실험은변경·실행하지않는다. 기존성능결과를새실험처럼갱신하지않는다.

재현·분석검증과제출본재생성결과는작업완료시검증JSON에기록한다. 예전v2제출복사본은삭제전보존본이며최신제출본과구분한다.
