#!/usr/bin/env python3
"""After queued fresh control N10: add N20, then selected N30 and paced checks."""
import argparse
import json
from run_sweep import ROOT, apply, measure, run

p = argparse.ArgumentParser()
p.add_argument('candidate')
a = p.parse_args()
# A previous serialized control run must have finished, with unchanged templates.
assert json.loads((ROOT / 'results/confirm-a-control/manifest.json').read_text())['state'] == 'PASS'
for model in ('qwen', 'yolo'):
    actual = json.loads(run(['kubectl', '-n', 'cj-inference', 'get', 'deployment', model, '-o', 'json'], capture_output=True).stdout)['spec']['template']
    assert actual == json.loads((ROOT / 'backup' / (model + '.json')).read_text())['spec']['template']
measure('control', 'confirm-a2-control', 20, 5)
try:
    apply(a.candidate)
    measure(a.candidate, 'confirm-b-' + a.candidate, 30, 5)
    # Same-pod confirmation under a common CV launch ceiling. Still C1, not open-loop.
    measure(a.candidate, 'confirm-c-' + a.candidate + '-paced20', 10, 5, cv_rate=20)
finally:
    apply('control')
measure('control', 'confirm-d-control-paced20', 10, 5, cv_rate=20)
