#!/bin/bash
set -eo pipefail
R=$HOME/cj-optimization/20261104-v1
while pgrep -u "$(id -u)" -f '^python3 /home/avees/cj-optimization/20261104-v1/src/run_sweep.py mps ' >/dev/null; do sleep 10; done
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
