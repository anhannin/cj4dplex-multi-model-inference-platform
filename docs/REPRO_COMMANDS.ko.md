# 과거 최적화 단계의 직접 재현 명령

PID를기다리는일회성실행기는활성소스에서제거했다. 실험본체·입력·설정은유지한다. 아래는삭제된wrapper에서대기루프를제외한실제호출이다. 과거호스트경로이므로새서버준비/백업/권한/유휴GPU확인후경로를맞춘다. 현재서버에자동실행하지않는다.

## confirm_control_after_factorial.sh

```bash
set -eo pipefail
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
```

## export_after_sweep.sh

```bash
set -eo pipefail
R=$HOME/cj-optimization/20261104-v1
mkdir -p "$R/engine"
date -Is > "$R/results/trt-export-start.txt"
timeout 1200 docker run --rm --name cj-trt-export --gpus all --network none --user 1000:1000 \
  -e HOME=/tmp -e YOLO_CONFIG_DIR=/tmp/yolo -e YOLO_AUTOINSTALL=false \
  -v "$R:/experiment" -v "$HOME/cj-containers/assets:/assets:ro" \
  --entrypoint python cj-yolo-ros:26l-timing-v1 /experiment/src/export_trt.py > "$R/results/trt-export.log" 2>&1
# Export and fidelity validation are serialized after all screening measurements.
timeout 180 docker run --rm --name cj-trt-quality --gpus all --network none --user 1000:1000 \
  -e HOME=/tmp -e YOLO_CONFIG_DIR=/tmp/yolo -e YOLO_AUTOINSTALL=false \
  -v "$R:/experiment" -v "$HOME/cj-containers/assets:/assets:ro" \
  --entrypoint python cj-yolo-ros:26l-timing-v1 /experiment/src/quality_trt.py > "$R/results/trt-quality.log" 2>&1
```

## final_after_control.sh

```bash
set -eo pipefail
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-optimization/20261104-v1/src
python3 -u final_confirmation.py trt-dds-mps-q50 > ../results/final-confirmation.log 2>&1
```

## probe_green_mapping_after_backend.sh

```bash
set -eo pipefail
R=$HOME/cj-optimization/20261104-v1
G=$HOME/cj-green-context/20261103-v1
# Serialized after backend sweep and before any later manually started GPU work.
timeout 90 docker run --rm --name cj-green-mps-mapping --gpus all --network none --user 1000:1000 \
  -e HOME=/tmp -e PYTHONPATH=/diag/src -e CUDA_MPS_PIPE_DIRECTORY=$R/mps-pipe \
  -v "$G:/diag:ro" -v "$R:/experiment" -v "$R/mps-pipe:$R/mps-pipe" \
  --entrypoint python cj-yolo-ros:26l-timing-v1 /diag/src/cross_process_probe.py \
  --output /experiment/results/green-mps-mapping > "$R/results/green-mps-mapping.log" 2>&1
```

## run_remaining_after_probe.sh

```bash
set -eo pipefail
source ~/.config/cj-ros2/spark-jazzy.bash
python3 ~/cj-optimization/20261104-v1/src/run_sweep.py trt-dds dds-mps-q50 --prefix factorial \
 > ~/cj-optimization/20261104-v1/results/factorial-sweep.log 2>&1
```
