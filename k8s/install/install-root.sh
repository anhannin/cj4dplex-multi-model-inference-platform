#!/usr/bin/env bash
set -Eeuo pipefail
exec 3>&1
umask 077
log=/var/log/cj-k8s-install.log
exec >>"$log" 2>&1
stage() { echo "STAGE: $*" >&3; echo "$(date -Is) $*"; }
trap 'echo "INSTALL_FAILED line=$LINENO; root-only log: /var/log/cj-k8s-install.log" >&3' ERR
[[ $(id -u) == 0 ]]
[[ ! -e /etc/kubernetes/admin.conf ]]
[[ ! -e /etc/containerd-k8s/config.toml ]]
[[ -z $(nvidia-smi --query-compute-apps=pid --format=csv,noheader) ]]
base=/home/avees/cj-k8s
mkdir -p "$base/evidence" /etc/containerd-k8s/conf.d /etc/apt/keyrings
cp -a /etc/containerd/config.toml /etc/docker/daemon.json /etc/fstab "$base/evidence/" 2>/dev/null || true
sha256sum /etc/containerd/config.toml /etc/docker/daemon.json > "$base/evidence/docker-config-before.sha256"
ufw status verbose > "$base/evidence/ufw-before.txt"
stage 'Installing pinned Kubernetes 1.37.2 packages'
curl -fsSL --retry 3 https://pkgs.k8s.io/core:/stable:/v1.37/deb/Release.key | gpg --dearmor --batch --yes -o /etc/apt/keyrings/cj-kubernetes.gpg
echo 'deb [signed-by=/etc/apt/keyrings/cj-kubernetes.gpg] https://pkgs.k8s.io/core:/stable:/v1.37/deb/ /' > /etc/apt/sources.list.d/cj-kubernetes.list
chmod 644 /etc/apt/keyrings/cj-kubernetes.gpg /etc/apt/sources.list.d/cj-kubernetes.list
apt-get update -o Dir::Etc::sourcelist=sources.list.d/cj-kubernetes.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
version=$(apt-cache madison kubeadm | awk '$3 ~ /^1\.37\.2-/ && !found { print $3; found=1 }')
[[ -n "$version" ]]
DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y kubeadm="$version" kubelet="$version" kubectl="$version" cri-tools
apt-mark hold kubelet kubeadm kubectl
stage 'Configuring independent Kubernetes containerd (Docker unchanged)'
modprobe overlay
modprobe br_netfilter
printf 'overlay\nbr_netfilter\n' > /etc/modules-load.d/cj-kubernetes.conf
cat > /etc/sysctl.d/90-cj-kubernetes.conf <<'CFG'
net.ipv4.ip_forward=1
net.bridge.bridge-nf-call-iptables=1
net.bridge.bridge-nf-call-ip6tables=1
CFG
sysctl -p /etc/sysctl.d/90-cj-kubernetes.conf
containerd config default > /etc/containerd-k8s/config.toml
python3 - <<'PY'
from pathlib import Path
import tomllib
p=Path('/etc/containerd-k8s/config.toml')
s=p.read_text().replace("root = '/var/lib/containerd'", "root = '/var/lib/containerd-k8s'",1)
s=s.replace("state = '/run/containerd'", "state = '/run/containerd-k8s'",1)
s=s.replace("address = '/run/containerd/containerd.sock'", "address = '/run/containerd-k8s/containerd.sock'",1)
s=s.replace("imports = ['/etc/containerd/conf.d/*.toml']", 'imports = []',1)
s=s.replace('SystemdCgroup = false','SystemdCgroup = true')
s=s.replace('registry.k8s.io/pause:3.10.1', 'registry.k8s.io/pause:3.10.2')
s=s.replace("path = '/opt/containerd'", "path = '/opt/containerd-k8s'")
d=tomllib.loads(s)
assert d['root']=='/var/lib/containerd-k8s'
assert d['state']=='/run/containerd-k8s'
assert d['plugins']['io.containerd.cri.v1.runtime']['containerd']['runtimes']['runc']['options']['SystemdCgroup']
p.write_text(s)
PY
nvidia-ctk runtime configure --runtime=containerd --config=/etc/containerd-k8s/config.toml --drop-in-config=/etc/containerd-k8s/conf.d/99-nvidia.toml
cat > /etc/systemd/system/containerd-k8s.service <<'UNIT'
[Unit]
Description=Isolated containerd for Kubernetes (CJ)
After=network.target
[Service]
Type=notify
ExecStart=/usr/bin/containerd --config /etc/containerd-k8s/config.toml
Delegate=yes
KillMode=process
Restart=always
RestartSec=5
LimitNOFILE=infinity
LimitNPROC=infinity
LimitCORE=infinity
TasksMax=infinity
[Install]
WantedBy=multi-user.target
UNIT
chmod 644 /etc/systemd/system/containerd-k8s.service /etc/modules-load.d/cj-kubernetes.conf /etc/sysctl.d/90-cj-kubernetes.conf
systemctl daemon-reload
systemctl enable --now containerd-k8s
cat > /etc/crictl.yaml <<'CFG'
runtime-endpoint: unix:///run/containerd-k8s/containerd.sock
image-endpoint: unix:///run/containerd-k8s/containerd.sock
timeout: 20
CFG
crictl info > "$base/evidence/cri-info.json"
# Keep host swap intact; official kubelet NoSwap prevents Kubernetes pods using it.
cat > "$base/kubeadm.yaml" <<'CFG'
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: 192.168.24.204
  bindPort: 6443
nodeRegistration:
  name: spark-e6d6
  criSocket: unix:///run/containerd-k8s/containerd.sock
  kubeletExtraArgs:
  - name: node-ip
    value: 192.168.24.204
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: v1.37.2
clusterName: cj-spark
networking:
  podSubnet: 10.244.0.0/16
  serviceSubnet: 10.96.0.0/12
---
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: systemd
failSwapOn: false
memorySwap:
  swapBehavior: NoSwap
CFG
# Add scoped Pod-network rules; retain UFW and existing ingress restrictions.
ufw allow in on cni0 comment 'CJ Kubernetes CNI'
ufw allow in on flannel.1 comment 'CJ Kubernetes Flannel'
ufw allow from 10.244.0.0/16 comment 'CJ Kubernetes Pods to host'
ufw route allow from 10.244.0.0/16 comment 'CJ Kubernetes Pod routing'
stage 'Initializing single-node control plane'
kubeadm init --config "$base/kubeadm.yaml"
install -d -m 700 -o avees -g avees /home/avees/.kube
install -m 600 -o avees -g avees /etc/kubernetes/admin.conf /home/avees/.kube/config
export KUBECONFIG=/etc/kubernetes/admin.conf
kubectl taint nodes spark-e6d6 node-role.kubernetes.io/control-plane:NoSchedule-
curl -fsSL --retry 3 https://github.com/flannel-io/flannel/releases/download/v0.28.10/kube-flannel.yml -o "$base/flannel-v0.28.10.yaml"
kubectl apply -f "$base/flannel-v0.28.10.yaml"
kubectl wait --for=condition=Ready node/spark-e6d6 --timeout=300s
kubectl -n kube-system rollout status deployment/coredns --timeout=300s
stage 'CPU control plane and CNI Ready'
sha256sum -c "$base/evidence/docker-config-before.sha256"
kubectl get nodes -o wide > "$base/evidence/nodes.txt"
kubectl get pods -A -o wide > "$base/evidence/system-pods.txt"
ufw status verbose > "$base/evidence/ufw-after.txt"
echo COMPLETE > "$base/evidence/install-status.txt"
chown -R avees:avees "$base/evidence"
stage 'INSTALL_COMPLETE; user kubectl configured; Docker configuration hashes unchanged'
