"""Check idle co-resident CV handshake tails; change YOLO/client only, Qwen remains idle."""
import json
import subprocess
from overlays import candidate_template, template_patch
from run_sweep import ROOT, measure, run


def yolo_apply(candidate):
    original = json.loads((ROOT / 'backup/yolo.json').read_text())['spec']['template']
    patch = ROOT / 'config/yolo-tail-active.json'
    patch.write_text(json.dumps(template_patch(candidate_template(original, candidate, 'yolo', str(ROOT)))))
    run(['kubectl', '-n', 'cj-inference', 'patch', 'deployment', 'yolo', '--type=json', '--patch-file', str(patch)], stdout=subprocess.DEVNULL)
    run(['kubectl', '-n', 'cj-inference', 'rollout', 'status', 'deployment/yolo', '--timeout=120s'])


try:
    for index, candidate in enumerate(('control', 'dds', 'control', 'dds')):
        yolo_apply(candidate)
        measure(candidate, f'idle-cv-{index:02d}-{candidate}', 500, 5, models='yolo')
finally:
    yolo_apply('control')
