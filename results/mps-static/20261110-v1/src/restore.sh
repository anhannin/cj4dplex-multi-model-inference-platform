#!/usr/bin/env bash
set -eo pipefail
unset CUDA_MPS_SM_PARTITION CUDA_MPS_PIPE_DIRECTORY LD_LIBRARY_PATH
source "$HOME/.config/cj-ros2/spark-jazzy.bash"
export GREEN_BURST_ROOT="$HOME/cj-mps-static/20261110-v1"
export PYTHONPATH="$HOME/cj-mps-burst/20261110-v1/src:${PYTHONPATH:-}"
systemctl --user start cj-cuda-mps.service
python3 -u - <<'PY'
import json,time
import base_runner as base
state={'state':'RUNNING','start_wall_ns':time.time_ns()}
file=base.ROOT/'verification/original-serving-restoration.json'
file.write_text(json.dumps(state,indent=2))
try:
    backups={m:json.loads((base.ROOT/'backup'/f'{m}.json').read_text()) for m in ('qwen','yolo')}
    base.restore(backups)
    state['state']='PASS'
except BaseException as e:
    state.update(state='FAIL',error=repr(e))
    raise
finally:
    state['end_wall_ns']=time.time_ns()
    file.write_text(json.dumps(state,indent=2))
print(json.dumps(state),flush=True)
PY
