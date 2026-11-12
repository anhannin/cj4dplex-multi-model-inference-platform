#!/bin/bash
set -eo pipefail
while pgrep -u "$(id -u)" -f '^bash /home/avees/cj-optimization/20261104-v1/src/probe_green_mapping_after_backend.sh' >/dev/null; do sleep 10; done
source ~/.config/cj-ros2/spark-jazzy.bash
python3 ~/cj-optimization/20261104-v1/src/run_sweep.py trt-dds dds-mps-q50 --prefix factorial \
 > ~/cj-optimization/20261104-v1/results/factorial-sweep.log 2>&1
