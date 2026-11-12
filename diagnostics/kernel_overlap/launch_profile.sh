#!/usr/bin/env bash
set -eo pipefail
model="$1"
case_label="$2"
source /opt/ros/jazzy/setup.bash
mkdir -p "/experiment/validation/$case_label/$model" /runtime/nsys-tmp
export TMPDIR=/runtime/nsys-tmp
cleanup(){ if [[ -s /tmp/cj-model-ready ]]; then kill -INT "$(cat /tmp/cj-model-ready)" 2>/dev/null || true; fi; }
trap cleanup TERM INT EXIT
nsys profile --session-new="overlap-$case_label-$model" --trace=cuda,nvtx --sample=none --cpuctxsw=none --capture-range=cudaProfilerApi --capture-range-end=stop --kill=none --output="/experiment/validation/$case_label/$model/trace" python "/experiment/src/${model}_overlap_node.py" --ros-args -p "queue_capacity:=$([[ $model == qwen ]] && echo 16 || echo 512)" &
profiler=$!
while kill -0 "$profiler" 2>/dev/null; do sleep 1; done
code=0;wait "$profiler" || code=$?
if [[ $code != 0 ]]; then exit "$code"; fi
while [[ -s /tmp/cj-model-ready ]] && kill -0 "$(cat /tmp/cj-model-ready)" 2>/dev/null; do sleep 1; done
