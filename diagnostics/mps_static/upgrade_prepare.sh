#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]]
R=/home/avees/cj-mps-static/20261110-v1
B=/var/backups/cj-driver-upgrade-20261110
mkdir -p "$B" "$R/rollback-debs"
chmod 700 "$B" "$R/rollback-debs"
cp -a /var/lib/dpkg/status "$B/dpkg-status"
tar -cpf "$B/system-config.tar" /etc/default/grub /etc/default/grub.d /etc/netplan /etc/NetworkManager/system-connections /boot/grub/grub.cfg /boot/grub/grubenv 2>"$B/tar-warnings.log"
cp -a /boot/vmlinuz-6.17.0-1031-nvidia /boot/initrd.img-6.17.0-1031-nvidia "$B/"
efibootmgr -v > "$B/efi-boot.txt"
cd "$R/rollback-debs"
mapfile -t packages < <(sed -n 's/^Remv \([^ ]*\) .*/\1/p' "$R/verification/apt-simulation-595-explicit.txt" | sort -u)
[[ ${#packages[@]} == 16 ]]
"$R/repack-tool/usr/bin/dpkg-repack" --tag=none --deb-option=-Zgzip --deb-option=-z1 "${packages[@]}"
[[ $(find . -maxdepth 1 -name '*.deb' | wc -l) == 16 ]]
sha256sum ./*.deb > SHA256SUMS
# Private network/boot backups never enter the repository artifact directory.
printf 'ROLLBACK_PACKAGES=16\nROOT_SYSTEM_BACKUP=%s\n' "$B" > "$R/verification/rollback-ready.txt"
grep -E '^[[:space:]]*menuentry|^[[:space:]]*submenu' /boot/grub/grub.cfg > "$R/verification/grub-menu-before.txt"
echo UPGRADE_BACKUP_PASS
