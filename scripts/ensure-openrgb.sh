#!/usr/bin/env bash
# Ensure OpenRGB user service is enabled; restart only after udev rules change.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

udev_output="$(bash "$ROOT/scripts/install-openrgb-udev.sh")"
udev_changed=0
if printf '%s\n' "$udev_output" | grep -q 'UDEV_CHANGED=1'; then
  udev_changed=1
fi
printf '%s\n' "$udev_output" | grep -v '^UDEV_CHANGED='

service_file="/home/$STEAMOS_USER/.config/systemd/user/openrgb.service"
if [ ! -f "$service_file" ]; then
  echo "openrgb.service not found at $service_file"
  record_manual "Create OpenRGB user service" <<EOF
# Example unit at $service_file:
# [Unit]
# Description=OpenRGB
# After=default.target
#
# [Service]
# Type=oneshot
# ExecStartPre=/usr/bin/sleep 5
# ExecStart=/usr/bin/flatpak run --command=openrgb $OPENRGB_FLATPAK_ID --server --profile ramoff
# RemainAfterExit=yes
#
# [Install]
# WantedBy=default.target

export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user daemon-reload
systemctl --user enable --now openrgb.service
EOF
  exit 1
fi

if ! systemctl --user is-enabled openrgb.service >/dev/null 2>&1; then
  systemctl --user enable openrgb.service
  echo "Enabled openrgb.service."
else
  echo "openrgb.service already enabled."
fi

if [ "$udev_changed" -eq 1 ]; then
  systemctl --user restart openrgb.service || true
  echo "Restarted openrgb.service after udev rules update."
elif ! systemctl --user is-active openrgb.service >/dev/null 2>&1; then
  systemctl --user start openrgb.service || true
  echo "Started openrgb.service."
else
  echo "openrgb.service already active."
fi
