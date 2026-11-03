#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import tomllib
p=Path('/etc/containerd-k8s/config.toml')
s=p.read_text()
d=tomllib.loads(s)
image=d['plugins']['io.containerd.cri.v1.images']['pinned_images']['sandbox']
assert image in ['registry.k8s.io/pause:3.10.1','registry.k8s.io/pause:3.10.2']
p.write_text(s.replace('registry.k8s.io/pause:3.10.1','registry.k8s.io/pause:3.10.2'))
PY
chmod 644 /etc/systemd/system/containerd-k8s.service /etc/modules-load.d/cj-kubernetes.conf /etc/sysctl.d/90-cj-kubernetes.conf
systemctl restart containerd-k8s
systemctl is-active containerd-k8s docker containerd
