#!/usr/bin/env bash
set -eo pipefail
source "$HOME/.config/cj-ros2/spark-jazzy.bash"
export ROS_DOMAIN_ID=42
export GREEN_BURST_ROOT="$HOME/cj-serving/mps-green-v1"
export PYTHONPATH="$HOME/cj-mps-concurrency/20261110-v1/src:${PYTHONPATH:-}"
python3 -c "import rclpy"
exec python3 -u "$HOME/cj-serving/mps-green-v1/deploy.py"
