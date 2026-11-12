#!/bin/bash
set -eo pipefail
while pgrep -u "$(id -u)" -f '^bash /home/avees/cj-optimization/20261104-v1/src/run_remaining_after_probe.sh' >/dev/null; do sleep 10; done
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-optimization/20261104-v1/src
python3 -u - <<'PY' > ../results/confirm-control-driver.log 2>&1
import json
from run_sweep import ROOT, measure, run
for model in ('qwen', 'yolo'):
    actual = json.loads(run(['kubectl', '-n', 'cj-inference', 'get', 'deployment', model, '-o', 'json'], capture_output=True).stdout)['spec']['template']
    original = json.loads((ROOT / 'backup' / (model + '.json')).read_text())['spec']['template']
    assert actual == original, f'{model} not baseline; refuse control measurement'
measure('control', 'confirm-a-control', 10, 5)
PY
