#!/usr/bin/env bash
# Host-side BlueZ override for NUXBT. Must run on the host (not Distrobox).
# Drop-in is under /run (clears on reboot). Does not touch permanent /etc.
#
# SteamOS /usr is immutable — setcap on /usr/bin/python3 fails with
# "Read-only file system". Copy the interpreter into ~/code/nuxbt-host/bin
# and setcap that home copy instead (same pattern as sunshine-ds-kms).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

ACTION="${1:-}"
OVERRIDE_DIR=/run/systemd/system/bluetooth.service.d
OVERRIDE_PATH="$OVERRIDE_DIR/nuxbt.conf"

DIR="${NUXBT_HOST_DIR:-/home/${STEAMOS_USER}/code/nuxbt-host}"
VENV="$DIR/.venv"
SRC_PY="${NUXBT_PYTHON_SRC:-$(readlink -f /usr/bin/python3)}"
# Writable copy — file caps live here, never on /usr
CAP_PY="${NUXBT_PYTHON:-$DIR/bin/python3-nuxbt}"
CAPS='cap_net_raw,cap_net_admin,cap_net_bind_service+eip'

usage() {
  cat <<EOF
Usage: $0 enable|disable|status

enable   — tmpfs bluetoothd --compat --noplugin=*, setcap home python copy, restart BT
disable  — remove override, drop setcap on home copy, restart BT
status   — show override + bluetoothd args + python caps

Run on the host. Never setcap /usr/bin/python* (SteamOS root is read-only).
EOF
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "Re-run with sudo: sudo $0 $ACTION"
    exit 1
  fi
}

# Own as STEAMOS_USER so deck can exec without root.
ensure_cap_python() {
  if [ ! -x "$SRC_PY" ]; then
    echo "error: source python not found: $SRC_PY"
    return 1
  fi
  mkdir -p "$(dirname "$CAP_PY")"
  if [ ! -x "$CAP_PY" ] || ! cmp -s "$SRC_PY" "$CAP_PY"; then
    cp -a "$SRC_PY" "$CAP_PY"
    echo "copied $SRC_PY → $CAP_PY"
  fi
  # deck owns the tree; setcap needs root but keeps ownership
  chown "${STEAMOS_USER}:${STEAMOS_USER}" "$(dirname "$CAP_PY")" "$CAP_PY"
  /usr/bin/setcap "$CAPS" "$CAP_PY"
  # Point venv at the capped binary (shebangs follow bin/python)
  if [ -d "$VENV/bin" ]; then
    ln -sfn "$CAP_PY" "$VENV/bin/python"
    ln -sfn "$CAP_PY" "$VENV/bin/python3"
    # Keep a versioned name if present
    if [ -e "$VENV/bin/python3.14" ] || [ -L "$VENV/bin/python3.14" ]; then
      ln -sfn "$CAP_PY" "$VENV/bin/python3.14"
    fi
    chown -h "${STEAMOS_USER}:${STEAMOS_USER}" \
      "$VENV/bin/python" "$VENV/bin/python3" 2>/dev/null || true
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
  echo "python src: $SRC_PY"
  echo "python cap: $CAP_PY"
  if [ -x "$CAP_PY" ]; then
    echo "python caps: $(getcap "$CAP_PY" 2>/dev/null || echo none)"
  else
    echo "python caps: (missing — run enable)"
  fi
  if [ -L "$VENV/bin/python3" ]; then
    echo "venv python3 → $(readlink -f "$VENV/bin/python3" 2>/dev/null || readlink "$VENV/bin/python3")"
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
  ensure_cap_python
  systemctl daemon-reload
  systemctl restart bluetooth
  sleep 0.5
  status
  echo "NUXBT BlueZ override enabled (tmpfs; reboot clears override)."
  echo "File caps on $CAP_PY survive reboot; re-run enable after SteamOS updates if python changes."
}

disable_override() {
  need_root
  rm -f "$OVERRIDE_PATH"
  rmdir "$OVERRIDE_DIR" 2>/dev/null || true
  if [ -x "$CAP_PY" ]; then
    /usr/bin/setcap -r "$CAP_PY" 2>/dev/null || true
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
