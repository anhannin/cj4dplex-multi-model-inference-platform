#!/usr/bin/env bash
set -euo pipefail
# Run from the repository/build-context root on ARM64 Spark.
mkdir -p results
docker build --progress plain -f containers/common/Dockerfile -t cj-spark-base:25.09-cu130 . 2>&1 | tee results/build-base-final.log
docker build --progress plain -f containers/qwen/Dockerfile -t cj-qwen:9b-cu130 . 2>&1 | tee results/build-qwen-final.log
docker build --progress plain -f containers/yolo/Dockerfile -t cj-yolo:26l-cu130 . 2>&1 | tee results/build-yolo-final.log
for image in cj-qwen:9b-cu130 cj-yolo:26l-cu130; do
    docker run --rm --network none --entrypoint python "$image" -m pip check
done
