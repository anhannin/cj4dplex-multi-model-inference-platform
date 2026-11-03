#!/usr/bin/env bash
set -euo pipefail
# Run in the project build context on Spark; model parent images must already exist.
mkdir -p results
for image in cj-qwen:9b-cu130 cj-yolo:26l-cu130; do
    docker image inspect "$image" >/dev/null
done
docker build --progress plain -f containers/qwen/Dockerfile.api -t cj-qwen-api:9b-v1 . 2>&1 | tee results/build-qwen.log
docker build --progress plain -f containers/yolo/Dockerfile.api -t cj-yolo-api:26l-v1 . 2>&1 | tee results/build-yolo.log
