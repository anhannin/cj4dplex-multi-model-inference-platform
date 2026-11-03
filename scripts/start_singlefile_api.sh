#!/usr/bin/env bash
set -euo pipefail
root="${CJ_SINGLE_API_ROOT:-$HOME/cj-api-single}"
for name in cj-qwen-api-single cj-yolo-api-single; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Refusing to replace existing container: $name" >&2; exit 2
    fi
done
for port in 8001 8002; do
    if ss -lntH | awk -v port="$port" '$4 ~ ":" port "$" {busy=1} END {exit !busy}'; then
        echo "Port already in use: $port" >&2; exit 2
    fi
done
for image in cj-qwen-api:9b-single cj-yolo-api:26l-single; do
    docker image inspect "$image" >/dev/null
done
for kind in qwen yolo; do
    mkdir -p "$root/runtime/$kind"
    if [[ "$kind" == qwen ]]; then image=cj-qwen-api:9b-single; port=8001; else image=cj-yolo-api:26l-single; port=8002; fi
    docker run -d --init --name "cj-$kind-api-single" --gpus all --shm-size 2g \
        --user "$(id -u):$(id -g)" -p "127.0.0.1:$port:8000" \
        -e HOME=/runtime -e OMP_NUM_THREADS=4 -e PYTHONUNBUFFERED=1 \
        -e HF_HUB_OFFLINE=1 -e TRITON_CACHE_DIR=/runtime/triton \
        -e YOLO_CONFIG_DIR=/runtime/ultralytics -e QUEUE_CAPACITY="${QUEUE_CAPACITY:-8}" \
        -v "$root/runtime/$kind:/runtime" \
        -v "$HOME/.cache/huggingface/hub:/cache:ro" \
        -v "$HOME/cj-containers/assets:/assets:ro" "$image"
done
