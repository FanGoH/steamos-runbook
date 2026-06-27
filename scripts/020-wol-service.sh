#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set -a
source "$ROOT/.env"
set +a

SERVICE_FILE="/etc/systemd/system/wol.service"

apply_wol() {
  /usr/bin/ethtool -s "$STEAMOS_NIC_INTERFACE" wol g
}

current_wol() {
  /usr/bin/ethtool "$STEAMOS_NIC_INTERFACE" | awk -F': ' '/Wake-on:/ {print $2}'
}

if [ "${1:-}" = "--apply" ]; then
  apply_wol
  exit 0
fi

if ! command -v ethtool >/dev/null 2>&1; then
  echo "ethtool missing."
  echo "Install manually:"
  echo "  sudo steamos-readonly disable"
  echo "  sudo pacman -Sy ethtool"
  echo "  sudo steamos-readonly enable"
  exit 1
fi

sudo tee "$SERVICE_FILE" >/dev/null <<EOS
[Unit]
Description=Enable Wake-on-LAN
After=NetworkManager.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$STEAMOS_PLAYBOOK_DIR/scripts/020-wol-service.sh --apply
StandardOutput=append:$STEAMOS_PLAYBOOK_DIR/logs/wol-systemd.log
StandardError=append:$STEAMOS_PLAYBOOK_DIR/logs/wol-systemd.log
RemainAfterExit=yes

[Install]
WantedBy=graphical.target
EOS

sudo systemctl daemon-reload
sudo systemctl enable wol.service >/dev/null
sudo systemctl restart wol.service

if [ "$(current_wol)" = "g" ]; then
  echo "WoL enabled on $STEAMOS_NIC_INTERFACE."
else
  echo "WoL failed. Current Wake-on: $(current_wol)"
  exit 1
fi
