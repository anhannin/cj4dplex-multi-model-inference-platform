#!/usr/bin/env bash
set -euo pipefail
root="${CJ_CONTAINER_ROOT:-$HOME/cj-containers}"
for entry in 'qwen cj-qwen:9b-cu130' 'yolo cj-yolo:26l-cu130'; do
    read -r kind image <<< "$entry"
    name="cj-$kind-dev"
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Container already exists; refusing to replace it: $name" >&2
        exit 2
    fi
    home="$root/results/dev-$kind"
    mkdir -p "$home"
    docker run -d --init --name "$name" --gpus all --network none --shm-size 2g \
        --user "$(id -u):$(id -g)" -e HOME=/runtime \
        -e HF_HUB_OFFLINE=1 -e TRITON_CACHE_DIR=/runtime/triton \
        -e YOLO_CONFIG_DIR=/runtime/ultralytics \
        -v "$home:/runtime" -v "$root/scripts:/app/scripts" \
        -v "$root/assets:/assets:ro" \
        -v "$HOME/.cache/huggingface/hub:/cache:ro" \
        --entrypoint /usr/bin/sleep "$image" infinity
done
