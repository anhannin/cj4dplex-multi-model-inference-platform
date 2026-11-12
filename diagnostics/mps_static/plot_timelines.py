"""Recorded worker timelines with exact host clocks, not invented GPU execution bars."""

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from timeline_data import load_round

COLORS = {
    "preprocess": "#b0bec5",
    "first_token": "#08306b",
    "generation": "#4292c6",
    "predict": "#f28e2b",
    "postprocess": "#78909c",
    "publication": "#9564b5",
}
LABELS = {
    "preprocess": "입력 준비/전처리",
    "first_token": "첫 토큰 생성까지(호스트)",
    "generation": "나머지 토큰 생성",
    "predict": "YOLO predict() 호출",
    "postprocess": "출력 후처리",
    "publication": "결과 발행/ACK/정리",
}


def add_svg_titles(path, titles):
    ns = "http://www.w3.org/2000/svg"
    ET.register_namespace("", ns)
    tree = ET.parse(path)
    for item in tree.getroot().iter():
        name = item.attrib.get("id")
        if name in titles:
            title = ET.Element("{" + ns + "}title")
            title.text = titles[name]
            item.insert(0, title)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def draw_workers(cases, start, end, target):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Patch

    fig, ax = plt.subplots(figsize=(17, 7.5))
    ticks = []
    labels = []
    tips = {}
    for group, c in enumerate(cases):
        for offset, model in enumerate(("qwen", "yolo")):
            y = group * 3 + offset
            ticks.append(y)
            labels.append(c["title"] + "\n" + model.upper())
            ax.add_patch(
                Rectangle(
                    (start, y - 0.32), end - start, 0.64, color="#f2f2f2", linewidth=0
                )
            )
            lane = c["lanes"][model]
            for request in lane["requests"]:
                for number, phase in enumerate(request["phases"]):
                    a = max(start, phase["start"])
                    b = min(end, phase["end"])
                    if b <= a:
                        continue
                    rect = Rectangle(
                        (a, y - 0.32),
                        b - a,
                        0.64,
                        color=COLORS[phase["kind"]],
                        linewidth=0,
                    )
                    gid = f"{c['trial']}-{model}-{request['index']}-{number}"
                    rect.set_gid(gid)
                    ax.add_patch(rect)
                    tips[gid] = (
                        f"{c['trial']} | {model} #{request['index']} | {LABELS[phase['kind']]} | {phase['start']:.9f}–{phase['end']:.9f}s | {(phase['end'] - phase['start']) * 1000:.3f}ms | FIFO {request['queue_ms']:.3f}ms | UUID {request['id']}"
                    )
                if model == "qwen":
                    a = max(start, request["worker_start"])
                    b = min(end, request["worker_end"])
                    if b - a > (end - start) * 0.018:
                        ax.text(
                            (a + b) / 2,
                            y,
                            f"Q{request['index']}",
                            ha="center",
                            va="center",
                            fontsize=9,
                            color="white",
                        )
            received = lane["last_received"]
            if start <= received <= end:
                ax.plot(
                    [received, received],
                    [y - 0.46, y + 0.46],
                    color="#b2182b",
                    linestyle="--",
                    linewidth=1.2,
                )
                align = "right" if received > start + (end - start) * 0.8 else "left"
                ax.text(
                    received,
                    y - 0.5,
                    f"마지막 결과 {received:.3f}s",
                    ha=align,
                    va="bottom",
                    fontsize=9,
                    color="#b2182b",
                )
    ax.set_xlim(start, end)
    ax.set_ylim(7.6, -1.35)
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("각 burst 동시 발행 장벽(t0) 이후 시간 [초]")
    ax.grid(axis="x", alpha=0.23)
    legend = [Patch(facecolor=COLORS[k], label=LABELS[k]) for k in COLORS] + [
        Patch(facecolor="#f2f2f2", label="기록된 Worker 처리 구간 밖")
    ]
    fig.legend(
        handles=legend,
        loc="lower center",
        ncol=4,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.55, 0.01),
    )
    fig.suptitle(
        f"실제 Worker 처리 타임라인 — MPS 없음 / 일반 MPS / 정적 8·40SM\n동일 라운드 r{cases[0]['round']} 원시 로그 · 평균으로 만든 가상 타임라인 아님 · GPU 커널 점유 시간 아님",
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0.12, 1, 0.9))
    fig.savefig(target.with_suffix(".png"), dpi=170)
    fig.savefig(target.with_suffix(".svg"))
    plt.close(fig)
    add_svg_titles(target.with_suffix(".svg"), tips)


def draw_queues(cases, end, target):
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(6, 1, figsize=(16, 9), sharex=True)
    for group, c in enumerate(cases):
        for offset, model in enumerate(("qwen", "yolo")):
            ax = axes[group * 2 + offset]
            events = c["lanes"][model]["queue"]
            x = [0] + [p[0] for p in events] + [end]
            y = [0] + [p[1] for p in events] + [0]
            color = "#4292c6" if model == "qwen" else "#f28e2b"
            ax.step(x, y, where="post", color=color, linewidth=1.2)
            ax.fill_between(x, y, step="post", color=color, alpha=0.2)
            ax.set_ylabel(
                c["title"] + "\n" + model.upper(),
                rotation=0,
                ha="right",
                va="center",
                fontsize=9,
            )
            ax.text(
                0.99,
                0.77,
                f"최대 대기 {max(y)}개",
                transform=ax.transAxes,
                ha="right",
                fontsize=9,
            )
            ax.grid(alpha=0.2)
            ax.set_ylim(0, max(y) * 1.15 + 1)
    axes[-1].set_xlim(0, end)
    axes[-1].set_xlabel("각 burst t0 이후 시간 [초]")
    fig.suptitle(
        "실제 FIFO 대기 개수 — enqueue +1 / Worker 처리 시작 -1\n처리 중인 요청은 Queue 개수에 포함하지 않음; 모델별 y축 범위 다름",
        fontsize=13,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(target.with_suffix(".png"), dpi=170)
    fig.savefig(target.with_suffix(".svg"))
    plt.close(fig)


def html_file(data, path):
    template = """<!doctype html><html lang="ko"><meta charset="utf-8"><title>Multi-model Worker Timeline</title>
<style>body{font:14px system-ui,sans-serif;background:#fafafa;margin:24px;color:#20252a}h1{font-size:23px}button,input,select{font:inherit;margin:4px;padding:5px}input{width:100px}.controls,.legend{padding:10px;background:white;border:1px solid #ddd;border-radius:5px;margin:10px 0}.legend span{display:inline-block;margin:5px 12px 5px 0}.swatch{width:13px;height:13px;display:inline-block;margin-right:5px;vertical-align:middle}#chart{width:100%;height:480px;background:white;border:1px solid #ddd;touch-action:none}#queue{width:100%;height:300px;background:white;border:1px solid #ddd}.note{color:#555;font-size:13px;line-height:1.7}.tip{position:fixed;z-index:5;background:#17222eee;color:white;border-radius:4px;padding:9px;font-size:12px;pointer-events:none;display:none;white-space:pre-line;max-width:500px}.status{font-weight:bold;color:#274f6a}</style>
<h1>MPS 없음 / 일반 MPS / 정적 8·40 — 실제 Worker 처리 로그</h1>
<p class="note">GPU 커널 실행·점유 타임라인이 아닙니다. 모델 호출은 CPU 제어·GPU 대기 등을 포함합니다. 같은 라운드의 실제 기록을 t0에 맞췄으며 평균으로 합성하지 않았습니다.<br>막대에 마우스를 올리면 요청·단계·실제 시각·UUID를 확인할 수 있습니다. 마우스 휠: 시간 확대/축소, 드래그: 시간 이동.</p>
<div class="controls">라운드 <select id="round"></select><button id="full">전체</button><button id="thirty">0–30초</button><button id="half">0–0.5초</button>시작 <input id="start" type="number" step="0.01" value="0">끝 <input id="end" type="number" step="0.01"><button id="apply">적용</button><span class="status" id="range"></span></div>
<div class="legend" id="legend"></div><svg id="chart"></svg><h3>FIFO 대기 개수</h3><p class="note">enqueue +1 / Worker 처리 시작 -1. 처리 중인 요청은 제외하며 모델별 y축은 각 최대 대기에 맞춰 표시합니다.</p><svg id="queue"></svg><div id="tooltip" class="tip"></div>
<script>const DATA=__DATA__, COLORS=__COLORS__, LABELS=__LABELS__;let R=0,A=0,B=116;const NS='http://www.w3.org/2000/svg',L=180;let drag=null;
const by=id=>document.getElementById(id);function el(name,attrs,text){const n=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs||{}))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
function text(s,x,y,value,attrs={}){s.append(el('text',{x,y,'font-size':12,...attrs},value));}
function maximum(){return Math.max(...DATA[R].map(c=>c.makespan))+2;}
function tooltip(event,value){const t=by('tooltip');t.textContent=value;t.style.display='block';t.style.left=Math.min(event.clientX+14,window.innerWidth-510)+'px';t.style.top=Math.min(event.clientY+12,window.innerHeight-160)+'px';}
function draw(){const s=by('chart'),q=by('queue'),w=Math.max(800,s.clientWidth),end=maximum();B=Math.min(end,B);A=Math.max(0,Math.min(A,B-.001));const usable=w-L-30,x=t=>L+(t-A)/(B-A)*usable;s.innerHTML='';q.innerHTML='';s.setAttribute('viewBox',`0 0 ${w} 480`);q.setAttribute('viewBox',`0 0 ${w} 300`);by('start').value=A.toFixed(4);by('end').value=B.toFixed(4);by('range').textContent=` ${A.toFixed(3)}–${B.toFixed(3)}초`;
for(let k=0;k<=10;k++){const t=A+(B-A)*k/10;for(const v of [s,q])v.append(el('line',{x1:x(t),x2:x(t),y1:20,y2:v===s?438:260,stroke:'#ddd'}));text(s,x(t),460,t.toFixed(B-A<2?3:1),{'text-anchor':'middle'});text(q,x(t),282,t.toFixed(B-A<2?3:1),{'text-anchor':'middle'});}
DATA[R].forEach((c,g)=>['qwen','yolo'].forEach((m,z)=>{const i=g*2+z,y=52+i*62,lane=c.lanes[m];text(s,L-10,y+12,c.title,{'text-anchor':'end','font-size':11});text(s,L-10,y+28,m.toUpperCase(),{'text-anchor':'end','font-weight':'bold'});s.append(el('rect',{x:L,y,width:usable,height:32,fill:'#f2f2f2'}));
for(const r of lane.requests){for(const p of r.phases){const a=Math.max(A,p.start),b=Math.min(B,p.end);if(b<=a)continue;const box=el('rect',{x:x(a),y,width:x(b)-x(a),height:32,fill:COLORS[p.kind]});box.addEventListener('mousemove',e=>{if(!drag)tooltip(e,`${c.trial} | ${m.toUpperCase()} #${r.index}\n${LABELS[p.kind]}\n${p.start.toFixed(9)} – ${p.end.toFixed(9)}s\n구간 ${((p.end-p.start)*1000).toFixed(3)}ms\nFIFO ${r.queue_ms.toFixed(3)}ms\nUUID ${r.id}`);});box.addEventListener('mouseleave',()=>by('tooltip').style.display='none');s.append(box);}
if(m==='qwen'&&r.worker_end>A&&r.worker_start<B){const a=Math.max(A,r.worker_start),b=Math.min(B,r.worker_end);if((b-a)/(B-A)*usable>28)text(s,(x(a)+x(b))/2,y+21,'Q'+r.index,{'text-anchor':'middle',fill:'white','font-weight':'bold'});}}
if(lane.last_received>=A&&lane.last_received<=B){const xx=x(lane.last_received);s.append(el('line',{x1:xx,x2:xx,y1:y-5,y2:y+37,stroke:'#b2182b','stroke-dasharray':'4 3'}));text(s,Math.min(w-35,xx+4),y-7,`최종 수신 ${lane.last_received.toFixed(3)}s`,{'text-anchor':xx>w-220?'end':'start',fill:'#b2182b','font-size':11});}
const yy=26+i*37,h=25,peak=Math.max(...lane.queue.map(v=>v[1]));text(q,L-10,yy+11,c.title,{'text-anchor':'end','font-size':10});text(q,L-10,yy+25,`${m.toUpperCase()} 최대 ${peak}`,{'text-anchor':'end','font-size':10});q.append(el('rect',{x:L,y:yy,width:usable,height:h,fill:'#f6f6f6'}));let points=lane.queue,depth=0,prev=A,commands=`M ${x(A)} ${yy+h}`;for(const[t,d]of points){if(t<A){depth=d;continue;}if(t>B)break;commands+=` L ${x(prev)} ${yy+h-h*depth/Math.max(1,peak)} L ${x(t)} ${yy+h-h*depth/Math.max(1,peak)}`;prev=t;depth=d;}commands+=` L ${x(prev)} ${yy+h-h*depth/Math.max(1,peak)} L ${x(B)} ${yy+h-h*depth/Math.max(1,peak)} L ${x(B)} ${yy+h} Z`;q.append(el('path',{d:commands,fill:m==='qwen'?'#4292c6':'#f28e2b','fill-opacity':.28,stroke:m==='qwen'?'#4292c6':'#f28e2b','stroke-width':1}));}));}
for(let i=0;i<5;i++){const o=document.createElement('option');o.value=i;o.textContent='r'+i;by('round').append(o);}for(const[k,v]of Object.entries(COLORS)){const n=document.createElement('span');n.innerHTML=`<i class="swatch" style="background:${v}"></i>${LABELS[k]}`;by('legend').append(n);}by('legend').append(document.createTextNode('회색 배경: 기록된 처리 구간 밖 / 붉은 점선: 모델별 최종 결과 수신'));
by('round').onchange=()=>{R=+by('round').value;A=0;B=maximum();draw();};by('full').onclick=()=>{A=0;B=maximum();draw();};by('thirty').onclick=()=>{A=0;B=30;draw();};by('half').onclick=()=>{A=0;B=.5;draw();};by('apply').onclick=()=>{const a=+by('start').value,b=+by('end').value;if(Number.isFinite(a)&&Number.isFinite(b)&&b>a){A=a;B=b;draw();}};
by('chart').addEventListener('wheel',e=>{e.preventDefault();by('tooltip').style.display='none';const rect=by('chart').getBoundingClientRect(),ratio=Math.max(0,Math.min(1,(e.clientX-rect.left-L)/(rect.width-L-30))),span=B-A,width=Math.max(.001,Math.min(maximum(),span*Math.exp(e.deltaY*.0015))),center=A+ratio*span;A=Math.max(0,center-ratio*width);B=A+width;draw();},{passive:false});by('chart').onmousedown=e=>{drag={x:e.clientX,a:A,b:B};by('tooltip').style.display='none';};window.onmouseup=()=>drag=null;window.addEventListener('mousemove',e=>{if(!drag)return;const span=drag.b-drag.a,dx=(e.clientX-drag.x)/(by('chart').clientWidth-L-30)*span;A=Math.max(0,Math.min(maximum()-span,drag.a-dx));B=A+span;draw();});window.onresize=draw;B=maximum();draw();</script></html>"""
    path.write_text(
        template.replace("__DATA__", json.dumps(data, ensure_ascii=False))
        .replace("__COLORS__", json.dumps(COLORS))
        .replace("__LABELS__", json.dumps(LABELS, ensure_ascii=False))
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False}
    )
    data = [load_round(a.root, i) for i in range(5)]
    out = a.output
    out.mkdir(parents=True, exist_ok=True)
    full = max(c["makespan"] for cases in data for c in cases) + 3
    draw_workers(data[0], 0, full, out / "worker-full-r0")
    draw_workers(data[0], 0, 30, out / "worker-first30s-r0")
    draw_workers(data[0], 0, 0.5, out / "worker-first500ms-r0")
    draw_queues(data[0], full, out / "queue-depth-r0")
    (out / "timeline-data.json").write_text(
        json.dumps(
            {
                "clock": "hostCLOCK_MONOTONIC",
                "scope": "recordedworkerphasesNOTGPUkernels;allexistinglogs",
                "rounds": data,
            },
            ensure_ascii=False,
        )
    )
    html_file(data, out / "interactive-timeline.html")
    (out / "validation.json").write_text(
        json.dumps(
            {
                "state": "PASS",
                "rounds": 5,
                "settings": 3,
                "requests_per_setting_per_round": {"qwen": 10, "yolo": 300},
                "validated_requests": 4650,
                "selection": "round0fixedforPNGS;all5inHTML;notaveragetimeline",
                "no_new_experiments": True,
            },
            indent=2,
        )
    )
    print(out)


if __name__ == "__main__":
    main()
