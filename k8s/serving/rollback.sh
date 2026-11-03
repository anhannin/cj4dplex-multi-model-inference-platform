#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/cj-k8s-serving"
# Never restart Docker models while Kubernetes model processes may still exist.
kubectl -n cj-inference scale deployment/qwen deployment/yolo --replicas=0
kubectl -n cj-inference wait --for=delete pod -l 'app in (qwen,yolo)' --timeout=360s
# Use exact backed-up Pod template instead of blindly reverting unrelated revisions.
python3 - <<'PY'
import json
from pathlib import Path
# A JSON snapshot is written before cutover; this contains no kubeconfig/credentials.
old=json.loads(Path('backup/device-plugin.json').read_text())
Path('backup/plugin-restore-patch.json').write_text(json.dumps({'spec':{'template':old['spec']['template']}}))
PY
kubectl -n kube-system patch ds nvidia-device-plugin-daemonset --type merge --patch-file backup/plugin-restore-patch.json
kubectl -n kube-system rollout status ds/nvidia-device-plugin-daemonset --timeout=120s
kubectl -n kube-system delete configmap cj-gpu-sharing --ignore-not-found
docker start cj-qwen-ros cj-yolo-ros
