#!/bin/bash
set -eo pipefail
R=$HOME/cj-optimization/20261104-v1
G=$HOME/cj-green-context/20261103-v1
while pgrep -u "$(id -u)" -f '^python3 /home/avees/cj-optimization/20261104-v1/src/run_sweep.py trt ' >/dev/null; do sleep 10; done
# Serialized after backend sweep and before any later manually started GPU work.
timeout 90 docker run --rm --name cj-green-mps-mapping --gpus all --network none --user 1000:1000 \
  -e HOME=/tmp -e PYTHONPATH=/diag/src -e CUDA_MPS_PIPE_DIRECTORY=$R/mps-pipe \
  -v "$G:/diag:ro" -v "$R:/experiment" -v "$R/mps-pipe:$R/mps-pipe" \
  --entrypoint python cj-yolo-ros:26l-timing-v1 /diag/src/cross_process_probe.py \
  --output /experiment/results/green-mps-mapping > "$R/results/green-mps-mapping.log" 2>&1
