#!/usr/bin/env bash
set -eo pipefail
model="$1"
source /opt/ros/jazzy/setup.bash
mkdir -p "/experiment/validation/$model" /runtime/nsys-tmp
export TMPDIR=/runtime/nsys-tmp
cleanup() {
  if [[ -s /tmp/cj-model-ready ]]; then kill -INT "$(cat /tmp/cj-model-ready)" 2>/dev/null || true; fi
}
trap cleanup TERM INT EXIT
nsys profile --session-new="green-e2e-$model" --trace=cuda,nvtx --sample=none --cpuctxsw=none --capture-range=cudaProfilerApi --capture-range-end=stop --kill=none --output="/experiment/validation/$model/trace" python "/experiment/src/${model}_green_profile_node.py" &
profiler=$!
while kill -0 "$profiler" 2>/dev/null; do sleep 1; done
code=0; wait "$profiler" || code=$?
if [[ $code != 0 ]]; then exit "$code"; fi
while [[ -s /tmp/cj-model-ready ]] && kill -0 "$(cat /tmp/cj-model-ready)" 2>/dev/null; do sleep 1; done
