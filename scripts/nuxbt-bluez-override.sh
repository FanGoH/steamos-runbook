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
CONTAINER="${NUXBT_DISTROBOX:-steamos-tools}"
# NUXBT runs Distrobox Fedora /usr/bin/python3.12 (uv standalone Python lacks AF_BLUETOOTH).
PYTHON_BIN="${NUXBT_PYTHON:-/usr/bin/python3.12}"

usage() {
  cat <<EOF
Usage: $0 enable|disable|status

enable   — tmpfs bluetoothd --compat --noplugin=*, setcap on Distrobox python, restart BT
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
  if command -v distrobox >/dev/null 2>&1; then
    distrobox enter "$CONTAINER" -- bash -lc "getcap $PYTHON_BIN 2>/dev/null || echo python caps: none" 2>/dev/null \
      | sed 's/^/python caps: /' || echo "python caps: (distrobox unavailable)"
  fi
}

enable_override() {
  need_root
  mkdir -p "$OVERRIDE_DIR"
  cat >"$OVERRIDE_PATH" <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/lib/bluetooth/bluetoothd --compat --noplugin=*
EOF
  # setcap inside Distrobox (that is the interpreter NUXBT uses)
  if command -v distrobox >/dev/null 2>&1; then
    runuser -u "${STEAMOS_USER}" -- distrobox enter "$CONTAINER" -- \
      bash -lc "sudo setcap 'cap_net_raw,cap_net_admin,cap_net_bind_service+eip' $PYTHON_BIN && getcap $PYTHON_BIN" \
      || echo "warn: setcap inside Distrobox failed"
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
  if command -v distrobox >/dev/null 2>&1; then
    runuser -u "${STEAMOS_USER}" -- distrobox enter "$CONTAINER" -- \
      bash -lc "sudo setcap -r $PYTHON_BIN 2>/dev/null || true" || true
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
