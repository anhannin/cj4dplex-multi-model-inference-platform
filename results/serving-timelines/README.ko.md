# 기존 로그 기반 실제 Worker 타임라인

사용자 선택: **새로운 GPU 프로파일링/재실험 없이 기존 로그만 사용**. Spark의 배포·서빙 상태는 변경하지 않았다.

## 보기
- **[인터랙티브 HTML](20261110-v1/interactive-timeline.html)**: 브라우저로 열기. 휠 확대/축소, 드래그 이동, 시작/끝 시각 지정, r0–r4 전환, 구간 hover로 요청번호·UUID·실제시각·지속시간·FIFO대기 확인.
- [전체 Worker 타임라인 PNG](20261110-v1/worker-full-r0.png) / [SVG(hover정보)](20261110-v1/worker-full-r0.svg)
- [처음30초 확대](20261110-v1/worker-first30s-r0.png) / [SVG](20261110-v1/worker-first30s-r0.svg)
- [처음0.5초 확대](20261110-v1/worker-first500ms-r0.png) / [SVG](20261110-v1/worker-first500ms-r0.svg)
- [FIFO 대기 개수](20261110-v1/queue-depth-r0.png)
- [변환된 실제 구간 데이터](20261110-v1/timeline-data.json)

## 무엇을 나타내는가
**GPU 커널 점유 타임라인이 아니라 서버 Worker의 실제 처리 구간이다.** 같은라운드의 MPS없음/일반MPS/정적8·40을 각burst t0에 맞췄다. 단일설정안에서 Qwen·YOLO는 같은CLOCK_MONOTONIC 시간축을 쓴다. 서로다른설정의실험은 각각별도시각에실행됐으며그절대시각을동시에실행한것처럼해석하지않는다.

- 회색: 입력준비·전처리 또는 출력후처리.
- 짙은파랑: Qwen generate 시작부터 서버내첫생성토큰까지. 순수GPU-prefill 아님.
- 파랑: 이후토큰생성과generate 완료까지. CPU제어·GPU대기 포함.
- 주황: YOLO predict()호출. 내부전처리·forward·후처리·대기를포함하며순수GPU연산아님.
- 보라: 결과발행·ACK·Worker정리. 결과수신은ACK완료보다앞설수있다.
- 옅은배경: 기록된Worker처리구간밖. **GPU가idle이라는뜻아님.**
- 붉은점선: 해당모델의마지막클라이언트결과수신. 실제전체완료시간기준.

Q1–Q10은같은Qwen worker가FIFO로처리한요청번호다. YOLO의300개요청은짧은단계들이연속으로보인다. 모델호출막대가겹쳐도GPU실행의물리적동시성을이그림으로입증하지않는다. 실제GPU병렬성은별도Nsight자료와구분한다.

Queue는복수요청이동시에대기하기때문에Worker한레인에독점상태처럼칠하지않았다. 별도그래프는실제enqueue에+1/Worker시작에-1한대기개수며처리중요청은제외한다. Qwen과YOLO의y축범위도다르다.

## 사용한 실제 시각
`server_enqueued_perf_ns`, `server_started_perf_ns`, `model_start_perf_ns`, `model_end_perf_ns`, client `received_ns`가원시시각이다.
- 처리완료는`server_started + processing_ms`로복원.
- Worker종료는서버processing_finished로그의`worker_busy_ms`를`server_started`에더해복원.
- Q첫토큰시각은`server_enqueued + server_ttft_ms`로복원.

이elapsed기록으로복원한경계와직접기록한경계를구분한다. CUDA-event duration을임의로줄세워가짜GPU커널구간을만들지않았다.

## 라운드와 숫자
PNG/SVG는**사전에고정한r0 실제1회**다.5회평균으로만든가상타임라인이아니다. HTML은모든5라운드를전환할수있다.

| r0 실제1회 | Qwen10개 최종결과 | YOLO300개 최종결과 |
|---|---:|---:|
| MPS없음 |111.801초|15.735초|
| 일반MPS |111.240초|25.274초|
| 정적Q8/Y40 |111.582초|10.501초|

따라서이그림의10.501초는기존비교표의5회평균11.592초와다르며모순이아니다. 원본성능측정과집계표는 `../static-eval/README.ko.md`에있다.

## 검증 / 재생성
3설정×5라운드×310개=4,650요청에대해단계시각단조성,동일Worker작업비중첩,모델별10/300개수,최종수신과원시summary일치,Queue음수/미배출없음을검증했다. HTML은새의존성/CDN/네트워크요청없이동작한다.

```bash
python3 diagnostics/mps_static/plot_timelines.py \
 --root results/static-eval/20261110-v1 \
 --output results/serving-timelines/20261110-v1
.venv/bin/python -m unittest tests.test_serving_timeline -q
```

기존system Matplotlib/Noto폰트사용.149개전체테스트·Ruff·원본baseline677파일검사PASS. Chromium에서초기렌더링및r4전환/30초/0.5초/사용자범위/hover 실제동작을검증했다. 원본측정파일·서버구성·기존성능집계는변경하지않았다.
