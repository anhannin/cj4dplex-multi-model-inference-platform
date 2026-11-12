"""Independent CUPTI verification of actual model kernels; timing data is diagnostic."""
import argparse
import json
from pathlib import Path
import sqlite3


def verify(connection,label):
    spans=connection.execute('SELECT start,end FROM NVTX_EVENTS WHERE text=?',(label,)).fetchall()
    if len(spans)!=1:
        raise AssertionError((label,'ROI count',spans))
    lo,hi=spans[0]
    kernels=connection.execute('SELECT start,end,greenContextId FROM CUPTI_ACTIVITY_KIND_KERNEL WHERE start<? AND end>?',(hi,lo)).fetchall()
    if not kernels or any(a<lo or b>hi or c in (None,0) for a,b,c in kernels):
        raise AssertionError((label,'missing/cross-boundary/nonGreen model kernels',len(kernels)))
    counts={}
    for _,_,green in kernels:
        counts[green]=counts.get(green,0)+1
    return {'label':label,'kernels':len(kernels),'green_context_kernel_counts':counts,'all_roi_kernels_green':True}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('database',type=Path)
    p.add_argument('--model',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    with sqlite3.connect(a.database) as c:
        out={'state':'PASS','scope':'actual model kernel binding, not performance samples','checks':[verify(c,f'{a.model}.green.sm{sm}') for sm in (8,48)]}
    a.output.write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))
