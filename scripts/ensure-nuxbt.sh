#!/usr/bin/env bash
# Bring up host-native NUXBT for Switch 2 remote-play experiments.
# Additive only — does not enable switch2-controllers / nso-gc.
#
# Host SteamOS python3 has AF_BLUETOOTH. Distrobox cannot raw-HCI set_class
# (PermissionError → CoD stays 0x400000 → Switch ignores; phone still sees name).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_HOST_DIR:-/home/${STEAMOS_USER}/code/nuxbt-host}"
VENV="$DIR/.venv"
NUXBT="$VENV/bin/nuxbt"
OVERRIDE="$ROOT/scripts/nuxbt-bluez-override.sh"
HOST_PY="$(readlink -f /usr/bin/python3)"

mkdir -p "$DIR"

if ! "$HOST_PY" -c 'import socket; assert hasattr(socket, "AF_BLUETOOTH")'; then
  echo "Host $HOST_PY lacks AF_BLUETOOTH"
  exit 1
fi

if ! "$HOST_PY" -c 'import dbus, gi' 2>/dev/null; then
  echo "Need host packages: python-dbus python-gobject python-cairo"
  record_manual "Install NUXBT host Python deps" <<EOF
sudo pacman -S python-dbus python-gobject python-cairo
EOF
  exit 2
fi

if [ ! -x "$NUXBT" ]; then
  echo "Creating host venv at $DIR"
  "$HOST_PY" -m venv --system-site-packages "$VENV"
  "$VENV/bin/pip" install -U pip wheel
  "$VENV/bin/pip" install --no-deps nuxbt
  "$VENV/bin/pip" install 'Flask>=2.1.3' 'Flask-SocketIO>=5.3.4' 'blessed>=1.19.1' \
    'psutil>=5.9.0' 'pynput>=1.7.1' 'cryptography>=3.4' 'click>=8' 'a2wsgi' \
    'uvicorn>=0.38,<0.39'
fi

echo "NUXBT: $("$NUXBT" --version 2>/dev/null || true)"
"$OVERRIDE" status || true

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ] \
  || ! getcap "$HOST_PY" 2>/dev/null | grep -q cap_net_raw; then
  record_manual "Enable NUXBT BlueZ override + setcap on host python" <<EOF
systemctl --user stop nso-gc.service 2>/dev/null || true
sudo $OVERRIDE enable
# Confirms: override present + python caps include cap_net_raw
$OVERRIDE status

# Switch 2: Controllers → Change Grip/Order, then:
$ROOT/scripts/nuxbt-run.sh demo
EOF
  echo "Need: sudo $OVERRIDE enable  (sets BlueZ override + setcap on $HOST_PY)"
  exit 2
fi

echo "Ready. Open Switch 2 Change Grip/Order, then: $ROOT/scripts/nuxbt-run.sh demo"
exit 0
