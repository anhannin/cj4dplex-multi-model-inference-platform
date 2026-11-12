#!/bin/bash
set -eo pipefail
R=$HOME/cj-optimization/20261104-v1
export CUDA_MPS_PIPE_DIRECTORY=$R/mps-pipe
# No production CUDA clients modified. Probe is isolated, bounded, same UID, same image.
docker run --rm --name cj-mps-attach-probe --gpus all --user 1000:1000 \
  -e CUDA_MPS_PIPE_DIRECTORY -e HOME=/tmp -v "$R/mps-pipe:$R/mps-pipe" \
  --entrypoint python cj-yolo-ros:26l-timing-v1 -u -c \
  'import torch,time; x=torch.ones(1024,device="cuda"); print("CUDA_PROBE",x.sum().item(),flush=True); time.sleep(20)' > "$R/results/mps-probe-client.log" 2>&1 &
PID=$!
sleep 12
echo get_server_list | nvidia-cuda-mps-control > "$R/results/mps-probe-servers.txt"
while read -r SERVER; do
  [[ $SERVER =~ ^[0-9]+$ ]] && echo "get_client_list $SERVER" | nvidia-cuda-mps-control >> "$R/results/mps-probe-clients.txt"
done < "$R/results/mps-probe-servers.txt"
wait "$PID"
cat "$R/results/mps-probe-client.log" "$R/results/mps-probe-servers.txt" "$R/results/mps-probe-clients.txt"
