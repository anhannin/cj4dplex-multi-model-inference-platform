# 5.3절 그래프 재작성

- 목적: Qwen 전체응답 지연 유지와 YOLO tail 감소를 같은 요청 E2E p95로 전달한다.
- 범위: MPS없음 vs 정적8/40, 조건별5회 합산 Q50/Y1500요청. 평균·묶음완료·GPU순수시간으로 해석하지 않음.
- 보존: 원래7조건 그림과 원시자료를 수정/삭제하지 않는다. 본문5.3만 새PNG/SVG로 교체하고 상세자료는 링크로 둔다.
- 구현: scripts/plot_burst_report.py, stdlib 수치선택+선택적Matplotlib. 기존시스템Matplotlib3.1.2/Noto Sans CJK JP 사용; 새의존성 설치없음.
- 수치회귀2개 RED→GREEN: 정확한p95·두조건·sample수·감소율,필수조건없으면오류.
- 재생성: `/usr/bin/python3 scripts/plot_burst_report.py` (Matplotlib/CJK폰트가있는환경). 결과 docs/figures/의PNG/SVG와원본SHA포함JSON.
- 시각검증: 이미지확인, 한글/숫자/단위/제목·라벨 비중첩, 각축0시작·서로다른범위명시. visual-verdict96/pass로 .omx/state/burst-report-figure/ralph-progress.json에 기록.
