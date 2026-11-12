#!/bin/bash
set -eo pipefail
while pgrep -u "$(id -u)" -f '^bash /home/avees/cj-optimization/20261104-v1/src/confirm_control_after_factorial.sh' >/dev/null; do sleep 10; done
source ~/.config/cj-ros2/spark-jazzy.bash
cd ~/cj-optimization/20261104-v1/src
python3 -u final_confirmation.py trt-dds-mps-q50 > ../results/final-confirmation.log 2>&1
