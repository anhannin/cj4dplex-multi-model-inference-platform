#!/usr/bin/env bash
# Offline CPU-only Docker postprocessing, same profiler version as collection.
set -euo pipefail
root="$HOME/cj-nsys-diagnostics/20261103-v1"
docker run --rm --runtime=runc --network none --cap-drop ALL --user 1000:1000   -e HOME=/tmp -e NVIDIA_VISIBLE_DEVICES=void   -v "$root/reports:/profiles" -v "$root/evidence:/evidence"   --entrypoint /bin/bash cj-qwen-ros:baseline-20261103-v1 -c '
set -e
for model in qwen yolo; do
  index=0
  for phase in qwen-only yolo-only concurrent; do
    index=$((index+1))
    nsys export --type sqlite --output="/profiles/$model/$phase.sqlite"       "/profiles/$model/capture.$index.nsys-rep" > "/evidence/$phase-$model-export.log" 2>&1
    nsys stats --report cuda_gpu_kern_sum,cuda_api_sum,cuda_gpu_mem_time_sum,osrt_sum,nvtx_sum       --format csv "/profiles/$model/$phase.sqlite" > "/evidence/$phase-$model-stats.csv" 2>&1
    echo EXPORTED "$model" "$phase"
  done
done'
