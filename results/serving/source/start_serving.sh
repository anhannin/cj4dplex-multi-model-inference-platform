#!/usr/bin/env bash
set -euo pipefail
root="${CJ_SERVING_ROOT:-$HOME/cj-serving}"
assets="${CJ_ASSETS_ROOT:-$HOME/cj-containers/assets}"
cache="$HOME/.cache/huggingface/hub"
if [[ ! "${QUEUE_CAPACITY:-8}" =~ ^[1-9][0-9]*$ ]]; then
    echo 'QUEUE_CAPACITY must be a positive integer' >&2; exit 2
fi
if [[ -n $(nvidia-smi --query-compute-apps=pid --format=csv,noheader) ]]; then
    echo 'GPU compute workload already present; refusing to start additional models' >&2; exit 2
fi
# Preflight all names/ports/images before creating either container. Never replace existing ones.
for name in cj-qwen-api cj-yolo-api; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Refusing to replace existing container: $name" >&2; exit 2
    fi
done
for image in cj-qwen-api:9b-v1 cj-yolo-api:26l-v1; do
    docker image inspect "$image" >/dev/null
done
for port in 8001 8002; do
    if ss -lntH | awk -v port="$port" '$4 ~ ":" port "$" {busy=1} END {exit !busy}' ; then
        echo "Port already in use: $port" >&2; exit 2
    fi
done
test -f "$assets/yolo26l.pt"
test -d "$cache/models--Qwen--Qwen3.5-9B/snapshots/c202236235762e1c871ad0ccb60c8ee5ba337b9a"
for kind in qwen yolo; do
    home="$root/runtime/$kind"
    mkdir -p "$home"
    if [[ "$kind" == qwen ]]; then image=cj-qwen-api:9b-v1; port=8001; else image=cj-yolo-api:26l-v1; port=8002; fi
    docker run -d --init --name "cj-$kind-api" --gpus all --shm-size 2g \
        --user "$(id -u):$(id -g)" -p "127.0.0.1:$port:8000" \
        -e HOME=/runtime -e TRITON_CACHE_DIR=/runtime/triton \
        -e HF_HUB_OFFLINE=1 -e YOLO_CONFIG_DIR=/runtime/ultralytics \
        -e QUEUE_CAPACITY="${QUEUE_CAPACITY:-8}" \
        -v "$home:/runtime" -v "$assets:/assets:ro" -v "$cache:/cache:ro" \
        "$image"
done
