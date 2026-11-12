#!/usr/bin/env python3
"""CPU-only plot/report data generation from completed real-model sample files."""
import argparse
import csv
import json
from pathlib import Path
import statistics


def load(root,model):
    directory=root/'results'/('main-'+model)
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest['state']!='PASS':
        raise RuntimeError('Incomplete experiment: '+model)
    summary=json.loads((directory/'summary.json').read_text())
    default=json.loads((directory/'default-summary.json').read_text())[0]
    rows=[json.loads(line) for line in (directory/'requests.jsonl').read_text().splitlines()]
    expected=manifest['rounds']*manifest['samples_per_round']
    assert all(next(iter({v['n'] for k,v in point.items() if k!='sm_count'}))==expected for point in summary)
    assert len({point['sm_count'] for point in summary})==len(manifest['sms'])
    return {'manifest':manifest,'summary':summary,'default':default,'rows':rows}


def draw(ax, data, metric, title, ylabel, scale=1):
    points=data['summary']
    x=[r['sm_count'] for r in points]
    y=[r[metric]['mean']/scale for r in points]
    std=[r[metric]['std']/scale for r in points]
    ax.errorbar(x,y,yerr=std,color='#2468b4',marker='o',linewidth=2,capsize=3,label='Green context: mean +/- 1 SD')
    ref=data['default'][metric]['mean']/scale
    refstd=data['default'][metric]['std']/scale
    ax.axhline(ref,color='#555555',linestyle='--',linewidth=1.2,label='Default context (full 48 SM)')
    ax.axhspan(ref-refstd,ref+refstd,color='#777777',alpha=.09)
    for xx,yy,ss in zip(x,y,std):
        ax.annotate(f'{yy:.2f}',(xx,yy+ss),textcoords='offset points',xytext=(0,8),ha='center',fontsize=9)
    ax.set_title(title,fontsize=12)
    ax.set_xlabel('Allocated SM count (Green Context)')
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xlim(min(x)-2,max(x)+2)
    ax.set_ylim(0,max(max(v+s for v,s in zip(y,std)),ref+refstd)*1.25)
    ax.grid(axis='y',color='#dddddd',alpha=.7)
    ax.spines[['top','right']].set_visible(False)
    ax.legend(fontsize=8,loc='best')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    a=p.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    models={model:load(a.root,model) for model in ('yolo','qwen')}
    plots=a.root/'plots'
    plots.mkdir(exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'savefig.dpi':170})
    fig,axes=plt.subplots(1,3,figsize=(18,5.1))
    draw(axes[0],models['yolo'],'model_forward_ms','YOLO26l forward (640 x 640, batch 1)','CUDA-event forward span (ms)')
    draw(axes[1],models['qwen'],'prefill_forward_ms','Qwen3.5-9B prefill (512 input tokens)','CUDA-event forward span (ms)')
    draw(axes[2],models['qwen'],'decode_forward_ms_per_token','Qwen3.5-9B decode (127 one-token forwards)','CUDA-event forward span (ms/token)')
    fig.suptitle('Actual-model latency vs Green Context SM allocation on DGX Spark GB10',fontsize=15,y=.99)
    fig.text(.5,.015,'Qwen: 30 generations/SM; YOLO: 100 images/SM; two counterbalanced rounds. CUDA Graph OFF, MPS OFF. Device spans are not pure kernel-busy time or service E2E.',ha='center',fontsize=9)
    fig.tight_layout(rect=[0,.07,1,.94])
    for suffix in ('png','svg'):
        fig.savefig(plots/('sm-latency-model-stages.'+suffix))
    plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,9))
    draw(axes[0,0],models['yolo'],'predict_wall_ms','YOLO stock predict() wall time','Wall time through stream completion (ms)')
    draw(axes[0,1],models['qwen'],'generate_ttft_ms','Qwen generate() first-token latency','TTFT at stock streamer callback (ms)')
    draw(axes[1,0],models['qwen'],'tpot_ms','Qwen wall TPOT (127 token intervals)','Wall inter-token time (ms/token)')
    draw(axes[1,1],models['qwen'],'generate_wall_ms','Qwen stock generate() wall time (128 new tokens)','Generation wall time (s)',scale=1000)
    fig.suptitle('Stock-call wall timings: single active model, no ROS/API/queue',fontsize=14)
    fig.tight_layout(rect=[0,0,1,.96])
    for suffix in ('png','svg'):
        fig.savefig(plots/('sm-latency-wall.'+suffix))
    plt.close(fig)
    csvrows=[]
    analysis={}
    for model,data in models.items():
        analysis[model]={}
        for metric in (['model_forward_ms','predict_wall_ms'] if model=='yolo' else ['prefill_forward_ms','decode_forward_ms_per_token','decode_forward_total_ms','generate_ttft_ms','tpot_ms','generate_wall_ms']):
            full=next(r[metric]['mean'] for r in data['summary'] if r['sm_count']==48)
            analysis[model][metric]={'default_context_mean':data['default'][metric]['mean'],'green48_mean':full,'points':[]}
            for point in data['summary']:
                sm=point['sm_count']
                values=point[metric]
                per_round={}
                for round_index in range(data['manifest']['rounds']):
                    samples=[r[metric] for r in data['rows'] if not r['warmup'] and r['sm_count']==sm and r['round']==round_index]
                    per_round[str(round_index)]=statistics.mean(samples)
                row={'model':model,'sm_count':sm,'metric':metric,**values,'relative_to_green48':values['mean']/full,'round0_mean':per_round['0'],'round1_mean':per_round['1']}
                csvrows.append(row)
                analysis[model][metric]['points'].append(row)
            # Descriptive resource-efficiency heuristic, NOT a business SLO.
            within=[r['sm_count'] for r in analysis[model][metric]['points'] if r['mean']<=1.10*full]
            analysis[model][metric]['lowest_sampled_sms_within_10pct_of_green48']=min(within) if within else None
    with (plots/'sm-latency-summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(csvrows[0]))
        w.writeheader()
        w.writerows(csvrows)
    (plots/'analysis.json').write_text(json.dumps(analysis,indent=2))
    print(json.dumps({'state':'PASS','plots':str(plots)}))


if __name__=='__main__':
    main()
