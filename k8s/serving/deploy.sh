#!/usr/bin/env bash
# Run on Spark only, after image import. No root credential embedded.
set -euo pipefail
cd "$HOME/cj-k8s-serving"
kubectl get node spark-e6d6 >/dev/null
# Image import must have succeeded first (ctr requires sudo).
# An existing log alone is not proof of success: inspect the importer exit status.
test -s evidence/import.log
docker stop --timeout 300 cj-qwen-ros cj-yolo-ros | tee evidence/docker-stopped.txt
kubectl apply -f manifests/gpu-sharing.json
kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type strategic --patch-file manifests/device-plugin-patch.json
kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=120s
# Plugin Pod readiness precedes kubelet's asynchronous Node resource update.
for attempt in $(seq 1 30); do
    shared=$(kubectl get node spark-e6d6 -o jsonpath='{.status.allocatable.nvidia\.com/gpu\.shared}')
    [[ "$shared" == 2 ]] && break
    sleep 2
done
kubectl get node spark-e6d6 -o json > evidence/node-shared.json
python3 - <<'PY'
import json
n=json.load(open('evidence/node-shared.json'))
assert n['status']['allocatable'].get('nvidia.com/gpu.shared')=='2', n['status']['allocatable']
PY
kubectl apply -f manifests/probe-1.json -f manifests/probe-2.json
kubectl -n cj-inference wait --for=condition=Ready pod/gpu-probe-1 pod/gpu-probe-2 --timeout=120s
for i in 1 2; do kubectl -n cj-inference logs gpu-probe-$i > evidence/probe-$i.log; done
python3 - <<'PY'
from pathlib import Path
a=Path('evidence/probe-1.log').read_text().strip()
b=Path('evidence/probe-2.log').read_text().strip()
assert a.startswith('GPU-') and a==b,(a,b)
print('Same physical GPU:',a)
PY
kubectl -n cj-inference delete pod gpu-probe-1 gpu-probe-2 --wait=true --timeout=120s
kubectl apply -f manifests/qwen.json -f manifests/yolo.json
kubectl -n cj-inference wait --for=condition=Available deployment/qwen deployment/yolo --timeout=660s
kubectl -n cj-inference get pods -o wide | tee evidence/model-pods.txt
