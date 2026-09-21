#!/usr/bin/env bash
# Host-side BlueZ override for NUXBT. Must run on the host (not Distrobox).
# Drop-in is under /run (clears on reboot). Does not touch permanent /etc.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

ACTION="${1:-}"
OVERRIDE_DIR=/run/systemd/system/bluetooth.service.d
OVERRIDE_PATH="$OVERRIDE_DIR/nuxbt.conf"
PYTHON_BIN="${NUXBT_PYTHON:-/home/${STEAMOS_USER}/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12}"

usage() {
  cat <<EOF
Usage: $0 enable|disable|status

enable   — tmpfs bluetoothd --compat --noplugin=*, setcap on NUXBT python, restart BT
disable  — remove override, drop setcap, restart BT
status   — show override + bluetoothd args

Run on the host. Distrobox cannot systemctl-restart host bluetooth.
EOF
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Re-run with sudo: sudo $0 $ACTION"
    exit 1
  fi
}

status() {
  if [ -f "$OVERRIDE_PATH" ]; then
    echo "override: present ($OVERRIDE_PATH)"
    cat "$OVERRIDE_PATH"
  else
    echo "override: absent"
  fi
  echo "bluetoothd: $(ps -o args= -C bluetoothd 2>/dev/null || echo '(not running)')"
  if command -v getcap >/dev/null 2>&1 && [ -x "$PYTHON_BIN" ]; then
    echo "python caps: $(getcap "$PYTHON_BIN" 2>/dev/null || echo none)"
  fi
}

enable_override() {
  need_root
  mkdir -p "$OVERRIDE_DIR"
  # Clear ExecStart then set bluetoothd with NUXBT flags (same as nuxbt toggle).
  cat >"$OVERRIDE_PATH" <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/lib/bluetooth/bluetoothd --compat --noplugin=*
EOF
  if [ -x "$PYTHON_BIN" ]; then
    /usr/bin/setcap 'cap_net_raw,cap_net_admin,cap_net_bind_service+eip' "$PYTHON_BIN"
  else
    echo "warn: python not found at $PYTHON_BIN (setcap skipped)"
  fi
  systemctl daemon-reload
  systemctl restart bluetooth
  sleep 0.5
  status
  echo "NUXBT BlueZ override enabled (tmpfs; reboot clears it)."
}

disable_override() {
  need_root
  rm -f "$OVERRIDE_PATH"
  rmdir "$OVERRIDE_DIR" 2>/dev/null || true
  if [ -x "$PYTHON_BIN" ]; then
    /usr/bin/setcap -r "$PYTHON_BIN" 2>/dev/null || true
  fi
  systemctl daemon-reload
  systemctl restart bluetooth
  sleep 0.5
  status
  echo "NUXBT BlueZ override disabled."
}

case "$ACTION" in
  enable) enable_override ;;
  disable) disable_override ;;
  status) status ;;
  *) usage; exit 1 ;;
esac
