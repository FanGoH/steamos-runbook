#!/usr/bin/env bash
# Ensure OpenRGB user service is enabled; reinstall udev rules after SteamOS updates.
# After rules change (or service start), request an SDK "Rescan devices" so RAM/DIMMs
# show up without opening the GUI. OpenRGB has no `--rescan` CLI flag; the SDK on
# TCP :6742 is the supported non-GUI equivalent (not HTTP).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

OPENRGB_PROFILE="${OPENRGB_PROFILE:-ramoff}"
OPENRGB_SDK_HOST="${OPENRGB_SDK_HOST:-127.0.0.1}"
OPENRGB_SDK_PORT="${OPENRGB_SDK_PORT:-6742}"

udev_output="$(bash "$ROOT/scripts/install-openrgb-udev.sh")"
udev_changed=0
if printf '%s\n' "$udev_output" | grep -q 'UDEV_CHANGED=1'; then
  udev_changed=1
fi
printf '%s\n' "$udev_output" | grep -v '^UDEV_CHANGED='

if [ "$udev_changed" -eq 1 ] && command -v udevadm >/dev/null 2>&1; then
  sudo udevadm settle || true
  sleep 1
fi

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
# ExecStart=/usr/bin/flatpak run --command=openrgb $OPENRGB_FLATPAK_ID --server --profile ${OPENRGB_PROFILE}
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

need_rescan=0
if [ "$udev_changed" -eq 1 ]; then
  systemctl --user restart openrgb.service || true
  echo "Restarted openrgb.service after udev rules update."
  need_rescan=1
elif ! systemctl --user is-active openrgb.service >/dev/null 2>&1; then
  systemctl --user start openrgb.service || true
  echo "Started openrgb.service."
  need_rescan=1
else
  echo "openrgb.service already active."
  # Still rescan after SteamOS recovery — initial detect often misses DIMMs
  # until UI "Rescan devices" (or an SDK rescan) runs.
  need_rescan=1
fi

if [ "$need_rescan" -eq 1 ]; then
  echo "Waiting for OpenRGB SDK on ${OPENRGB_SDK_HOST}:${OPENRGB_SDK_PORT}..."
  if python3 "$ROOT/scripts/openrgb-rescan.py" \
    --host "$OPENRGB_SDK_HOST" \
    --port "$OPENRGB_SDK_PORT" \
    --profile "$OPENRGB_PROFILE" \
    --wait 3; then
    echo "OpenRGB device rescan requested (CLI equivalent of UI Rescan devices)."
  else
    echo "Warning: could not send OpenRGB SDK rescan."
    record_manual "Rescan OpenRGB devices (RAM not detected until this)" <<EOF
# With openrgb.service running, either open the UI and click "Rescan devices", or:
python3 $ROOT/scripts/openrgb-rescan.py --profile $OPENRGB_PROFILE
EOF
  fi
fi
