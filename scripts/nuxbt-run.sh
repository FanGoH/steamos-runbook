#!/usr/bin/env bash
# Run NUXBT on the HOST (not Distrobox).
# SteamOS /usr/bin/python3 has AF_BLUETOOTH; Distrobox cannot raw-HCI set_class
# (PermissionError) so Switch never sees CoD 0x002508.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_HOST_DIR:-/home/${STEAMOS_USER}/code/nuxbt-host}"
VENV="$DIR/.venv"
NUXBT="$VENV/bin/nuxbt"
# Real interpreter behind the venv (needs setcap for raw HCI)
HOST_PY="$(readlink -f /usr/bin/python3)"

if [ ! -x "$NUXBT" ]; then
  echo "Host NUXBT missing. Run: $ROOT/scripts/ensure-nuxbt.sh"
  exit 1
fi

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ]; then
  echo "Host BlueZ override not enabled."
  echo "Run: sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
  exit 2
fi

# Warn if setcap missing (set_class will fail silently for Switch)
if ! getcap "$HOST_PY" 2>/dev/null | grep -q cap_net_raw; then
  echo "warn: $HOST_PY lacks cap_net_raw — Switch may ignore wrong CoD."
  echo "      sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
fi

if [ "$#" -eq 0 ]; then
  set -- demo
fi

export PYTHONUNBUFFERED=1
export PATH="$VENV/bin:$PATH"
exec "$NUXBT" "$@"
