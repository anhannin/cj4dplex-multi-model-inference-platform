#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/cj-preflight"
# Refuse to start while a foreign compute process is present.
if nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q '[0-9]'; then
  echo 'GPU compute process already present; no experiment started' >&2
  exit 2
fi
docker image inspect dmd-qwen35:no-torchao --format '{{.Id}}' > results/image-id.txt
set +e
timeout --signal=TERM --kill-after=20 1800 docker run --rm --name cj-model-preflight \
  --gpus all --network none --user "$(id -u):$(id -g)" \
  -e HOME=/work -e OMP_NUM_THREADS=4 -e TOKENIZERS_PARALLELISM=false \
  -e HF_HUB_OFFLINE=1 -e YOLO_CONFIG_DIR=/work/.config/Ultralytics \
  -v "$HOME/cj-preflight:/work" \
  -v "$HOME/.cache/huggingface/hub:/cache:ro" \
  --entrypoint /work/venv/bin/python dmd-qwen35:no-torchao \
  /work/scripts/run_preflight.py --seconds 60
status=$?
if [ "$status" -eq 124 ] || [ "$status" -eq 137 ]; then
  docker stop --time 10 cj-model-preflight >/dev/null 2>&1 || true
fi
printf '%s\n' "$status" > results/exit-code.txt
exit "$status"
