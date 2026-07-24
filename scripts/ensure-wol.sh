#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SERVICE_FILE="/etc/systemd/system/wol.service"
ENABLE_WOL="$STEAMOS_PLAYBOOK_DIR/enable-wol.sh"

if [ ! -d "/sys/class/net/$STEAMOS_NIC_INTERFACE" ]; then
  echo "NIC $STEAMOS_NIC_INTERFACE not found; skipping WOL setup."
  record_manual "Verify ethernet interface for WOL" <<EOF
ip -br link
# Update STEAMOS_NIC_INTERFACE in .env if the NIC name changed (current: $STEAMOS_NIC_INTERFACE)
EOF
  exit 1
fi

if ! command -v ethtool >/dev/null 2>&1; then
  echo "ethtool missing; installing via playbook helper..."
  if ! bash "$ROOT/scripts/010-ethtool-present.sh"; then
    exit 1
  fi
fi

mkdir -p "$STEAMOS_PLAYBOOK_DIR/logs"

desired_unit="$(cat <<EOS
[Unit]
Description=Enable Wake-on-LAN
After=NetworkManager.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$ENABLE_WOL
StandardOutput=append:$STEAMOS_PLAYBOOK_DIR/logs/wol-systemd.log
StandardError=append:$STEAMOS_PLAYBOOK_DIR/logs/wol-systemd.log
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
EOS
)"

if [ ! -f "$SERVICE_FILE" ] || [ "$(sudo cat "$SERVICE_FILE")" != "$desired_unit" ]; then
  printf '%s\n' "$desired_unit" | sudo tee "$SERVICE_FILE" >/dev/null
  sudo systemctl daemon-reload
  echo "Updated wol.service."
fi

if ! systemctl is-enabled wol.service >/dev/null 2>&1; then
  sudo systemctl enable wol.service
  echo "Enabled wol.service."
else
  echo "wol.service already enabled."
fi

sudo systemctl restart wol.service

current_wol="$(sudo ethtool "$STEAMOS_NIC_INTERFACE" 2>/dev/null | awk -F': ' '/^[[:space:]]*Wake-on:/{print $2; exit}' | tr -d '[:space:]')"
if [ "$current_wol" = "g" ]; then
  echo "WoL enabled on $STEAMOS_NIC_INTERFACE (Wake-on: g)."
else
  echo "WoL not set correctly on $STEAMOS_NIC_INTERFACE (Wake-on: ${current_wol:-unknown})."
  exit 1
fi
