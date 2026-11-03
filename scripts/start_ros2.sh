#!/usr/bin/env bash
set -euo pipefail
root="${CJ_ROS_ROOT:-$HOME/cj-ros2}"
for name in cj-qwen-ros cj-yolo-ros; do
    if docker container inspect "$name" >/dev/null 2>&1; then
        echo "Refusing to replace existing container: $name" >&2; exit 2
    fi
done
for image in cj-qwen-ros:9b-eos cj-yolo-ros:26l-uuid; do
    docker image inspect "$image" >/dev/null
done
if [[ -n $(nvidia-smi --query-compute-apps=pid --format=csv,noheader) ]]; then
    echo 'GPU compute processes exist; stop only the intended old serving instances first' >&2; exit 2
fi
for kind in qwen yolo; do
    mkdir -p "$root/runtime/$kind"
    if [[ "$kind" == qwen ]]; then image=cj-qwen-ros:9b-eos; else image=cj-yolo-ros:26l-uuid; fi
    docker run -d --init --name "cj-$kind-ros" --gpus all --network host --ipc host \
        --user "$(id -u):$(id -g)" \
        -e HOME=/runtime -e PYTHONUNBUFFERED=1 -e OMP_NUM_THREADS=4 \
        -e HF_HUB_OFFLINE=1 -e TRITON_CACHE_DIR=/runtime/triton \
        -e YOLO_CONFIG_DIR=/runtime/ultralytics \
        -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-42}" -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
        -v "$root/runtime/$kind:/runtime" \
        -v "$HOME/.cache/huggingface/hub:/cache:ro" \
        -v "$HOME/cj-containers/assets:/assets:ro" "$image"
done
