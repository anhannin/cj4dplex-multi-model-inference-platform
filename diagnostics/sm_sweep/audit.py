"""Offline invariant audit; never rewrite raw samples or mix profiled/timed runs."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def audit_model(directory):
    m=json.loads((directory/'manifest.json').read_text())
    assert m['state']=='PASS'
    assert m['mps'] is False and m['graph_capture'] is False
    rows=[json.loads(line) for line in (directory/'requests.jsonl').read_text().splitlines()]
    references=[json.loads(line) for line in (directory/'default-reference.jsonl').read_text().splitlines()]
    expected=m['rounds']*m['samples_per_round']
    seen=set()
    for r in rows+references:
        key=(r['backend'],r['round'],r['sm_count'],r['index'])
        assert key not in seen,('duplicate',key)
        seen.add(key)
        if m['model']=='qwen':
            assert r['output_tokens']==128
            assert r['forward_input_lengths']==[512]+[1]*127
            assert len(r['forward_event_ms'])==128
            assert all(math.isfinite(x) and x>0 for x in r['forward_event_ms'])
            assert abs(r['prefill_forward_ms']-r['forward_event_ms'][0])<1e-6
            assert abs(r['decode_forward_total_ms']-sum(r['forward_event_ms'][1:]))<1e-6
            assert abs(r['decode_forward_ms_per_token']-r['decode_forward_total_ms']/127)<1e-6
            assert sum(r['forward_event_ms'])<=r['generate_wall_ms']+1
            assert r['prefill_forward_ms']<=r['generate_ttft_ms']+1
        else:
            assert r['forward_shape']==[1,3,640,640]
            assert r['fidelity']['pass']
            assert 0<r['model_forward_ms']<=r['predict_wall_ms']+1
    for sm in m['sms']:
        selected=[r for r in rows if r['sm_count']==sm and not r['warmup']]
        assert len(selected)==expected
        for round_index in range(m['rounds']):
            assert len([r for r in selected if r['round']==round_index])==m['samples_per_round']
        resource=m['green_resources'][str(sm)]
        assert resource['actual_sms']==sm and resource['total_sms']==48
        assert resource['stream_owner_verified']
        assert 0<len(resource['observed_smids'])<=sm
    assert all(r['backend']=='green' for r in rows)
    assert all(r['backend']=='default' and r['sm_count']==48 for r in references)
    measured_references=[r for r in references if not r['warmup']]
    assert len(measured_references)==2*m['reference_samples_per_position']
    if m['model']=='qwen':
        w=m['workload']
        assert len(w['input_ids'])==512
        assert hashlib.sha256(json.dumps(w['input_ids']).encode()).hexdigest()==w['input_ids_sha256']
    return {'model':m['model'],'state':'PASS','measured_green':len([r for r in rows if not r['warmup']]),'warmup_green':len([r for r in rows if r['warmup']]),'measured_default':len(measured_references),'warmup_default':len([r for r in references if r['warmup']]),'fixed_work_and_native_stream_resource_checks':True}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    a=p.parse_args()
    out=[audit_model(a.root/'results'/('main-'+model)) for model in ('qwen','yolo')]
    (a.root/'verification/main-audit.json').write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))
