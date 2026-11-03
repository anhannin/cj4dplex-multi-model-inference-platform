#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl
curl -fL --retry 3 https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.noble_all.deb -o /tmp/ros2-apt-source.deb
dpkg -i /tmp/ros2-apt-source.deb
apt-get update
apt-get install -y --no-install-recommends ros-jazzy-ros-base ros-jazzy-std-msgs ros-jazzy-sensor-msgs
dpkg-query -W 'ros-jazzy-*' > /opt/ros-deb-versions.txt
rm -rf /var/lib/apt/lists/* /tmp/ros2-apt-source.deb
