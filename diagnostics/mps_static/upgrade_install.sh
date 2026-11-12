#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]]
R=/home/avees/cj-mps-static/20261110-v1
[[ -s "$R/verification/rollback-ready.txt" ]]
(cd "$R/rollback-debs"; sha256sum -c SHA256SUMS >/dev/null)
[[ $(uname -r) == 6.17.0-1031-nvidia ]]
UUID=$(grub-probe --target=fs_uuid /)
OLD="gnulinux-advanced-$UUID>gnulinux-6.17.0-1031-nvidia-advanced-$UUID"
NEW="gnulinux-advanced-$UUID>gnulinux-7.0.0-1025-nvidia-advanced-$UUID"
printf 'GRUB_DEFAULT=saved\nGRUB_SAVEDEFAULT=false\n' > /etc/default/grub.d/99-cj-driver-test.cfg
grub-set-default "$OLD"
packages=(nvidia-driver-580-open- nvidia-kernel-common-580- libnvidia-common-580-
 linux-modules-nvidia-595-open-7.0.0-1025-nvidia libnvidia-gl-595 libnvidia-compute-595
 libnvidia-extra-595 nvidia-compute-utils-595 libnvidia-decode-595 libnvidia-encode-595
 nvidia-utils-595 xserver-xorg-video-nvidia-595 libnvidia-cfg1-595 libnvidia-fbc1-595)
apt-get -s --no-install-recommends install "${packages[@]}" > "$R/verification/apt-final-simulation.txt"
! grep -q '^Inst nvidia-dkms' "$R/verification/apt-final-simulation.txt"
[[ $(grep -c '^Remv ' "$R/verification/apt-final-simulation.txt") == 16 ]]
systemctl stop display-manager
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l
apt-get install -y --no-install-recommends "${packages[@]}"
[[ -f /boot/vmlinuz-7.0.0-1025-nvidia ]]
[[ -s /boot/initrd.img-7.0.0-1025-nvidia ]]
[[ $(modinfo -k 7.0.0-1025-nvidia -F version nvidia) == 595.99.02 ]]
modinfo -k 7.0.0-1025-nvidia -F signer nvidia | grep -q 'Canonical'
! dpkg-query -W -f='${Status}' nvidia-dkms-595-open 2>/dev/null | grep -q 'install ok installed'
update-grub
grep -q "gnulinux-7.0.0-1025-nvidia-advanced-$UUID" /boot/grub/grub.cfg
grub-reboot "$NEW"
grub-editenv list > "$R/verification/grub-next-boot.txt"
printf 'DRIVER=595.99.02\nKERNEL=7.0.0-1025-nvidia\nSECUREBOOT_MODULE=Canonical\nFALLBACK=%s\nNEXT=%s\n' "$OLD" "$NEW" > "$R/verification/upgrade-ready-to-reboot.txt"
sync
echo SIGNED_DRIVER_KERNEL_INSTALL_PASS
