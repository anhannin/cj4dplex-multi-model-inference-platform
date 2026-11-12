"""Pure offline checks: fixed work, separated stages, descriptive statistics."""
import math
import random
import statistics


def summarize_forward(lengths, times, input_tokens, output_tokens):
    if len(lengths) != output_tokens or lengths != [input_tokens] + [1]*(output_tokens-1) or len(times) != len(lengths):
        raise ValueError('Expected one full-input prefill then output_tokens-1 one-token decode forwards')
    if any(not math.isfinite(t) or t <= 0 for t in times):
        raise ValueError('Invalid CUDA event duration')
    return {'prefill_forward_ms': times[0], 'decode_forward_total_ms': sum(times[1:]), 'decode_forward_ms_per_token': statistics.mean(times[1:]) if len(times)>1 else None, 'decode_forwards': len(times)-1}


def sweep_order(sms, round_index):
    values=list(sms)
    random.Random(20261109).shuffle(values)
    return values if round_index % 2 == 0 else list(reversed(values))


def fixed_prompt_ids(prefix, suffix, body, length):
    needed=length-len(prefix)-len(suffix)
    if needed <= 0 or len(body) < needed:
        raise ValueError('Insufficient prompt budget/body')
    return list(prefix)+list(body[:needed])+list(suffix)


def distribution(values):
    v=sorted(values)
    if not v or any(not math.isfinite(x) for x in v):
        raise ValueError('Finite nonempty samples required')
    pos=(len(v)-1)*.95
    lo=int(pos)
    return {'n':len(v),'mean':statistics.mean(v),'std':statistics.pstdev(v),'median':statistics.median(v),'p95':v[lo]+(v[min(lo+1,len(v)-1)]-v[lo])*(pos-lo),'min':v[0],'max':v[-1]}


def summarize_rows(rows, metrics):
    measured=[r for r in rows if not r.get('warmup')]
    result=[]
    for sm in sorted({r['sm_count'] for r in measured}):
        subset=[r for r in measured if r['sm_count']==sm]
        result.append({'sm_count':sm,**{key:distribution([r[key] for r in subset]) for key in metrics}})
    return result
