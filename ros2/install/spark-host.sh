#!/usr/bin/env bash
set -Eeuo pipefail
[[ $(id -u) == 0 ]]
. /etc/os-release
[[ "$VERSION_CODENAME" == noble ]]
[[ $(dpkg --print-architecture) == arm64 ]]
exec 3>&1
exec > /var/log/cj-spark-host-ros-install.log 2>&1
trap 'echo "HOST_ROS_INSTALL_FAILED line=$LINENO; log=/var/log/cj-spark-host-ros-install.log" >&3' ERR
base=/home/avees/cj-ros-host
mkdir -p "$base/evidence"
echo 'Installing native ROS2 Jazzy packages on Spark' >&3
curl -fL --retry 3 https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.noble_all.deb -o /tmp/cj-ros2-apt-source.deb
dpkg -i /tmp/cj-ros2-apt-source.deb
apt-get update
apt-get -s install --no-install-recommends ros-jazzy-ros-base ros-jazzy-std-msgs ros-jazzy-sensor-msgs > "$base/evidence/apt-simulation.txt"
if grep -E '^Inst (nvidia-|cuda-|docker|containerd|kubelet|kubeadm)' "$base/evidence/apt-simulation.txt"; then
    echo 'Refusing unexpected GPU/container/Kubernetes package changes' >&3
    exit 2
fi
DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --no-install-recommends ros-jazzy-ros-base ros-jazzy-std-msgs ros-jazzy-sensor-msgs
rm /tmp/cj-ros2-apt-source.deb
dpkg-query -W 'ros-jazzy-*' > "$base/evidence/ros-packages.txt"
systemctl is-active docker containerd containerd-k8s kubelet > "$base/evidence/services-after.txt"
chown -R avees:avees "$base/evidence"
echo 'HOST_ROS_PACKAGES_INSTALLED' >&3
