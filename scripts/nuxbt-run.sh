#!/usr/bin/env bash
# Run NUXBT on the HOST (not Distrobox).
# SteamOS /usr/bin/python3 has AF_BLUETOOTH; Distrobox cannot raw-HCI set_class
# (PermissionError) so Switch never sees CoD 0x002508.
# File caps live on ~/code/nuxbt-host/bin/python3-nuxbt (not /usr — immutable).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_HOST_DIR:-/home/${STEAMOS_USER}/code/nuxbt-host}"
VENV="$DIR/.venv"
NUXBT="$VENV/bin/nuxbt"
CAP_PY="${NUXBT_PYTHON:-$DIR/bin/python3-nuxbt}"

if [ ! -x "$NUXBT" ]; then
  echo "Host NUXBT missing. Run: $ROOT/scripts/ensure-nuxbt.sh"
  exit 1
fi

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ]; then
  echo "Host BlueZ override not enabled."
  echo "Run: sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
  exit 2
fi

# Warn if setcap missing (set_class send → PermissionError → CoD stays 0x400000)
if [ ! -x "$CAP_PY" ] || ! getcap "$CAP_PY" 2>/dev/null | grep -q cap_net_raw; then
  echo "warn: $CAP_PY lacks cap_net_raw — Switch may ignore wrong CoD."
  echo "      sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
  echo "      (SteamOS /usr is read-only; caps go on the home copy, not /usr/bin/python*)"
fi

if [ "$#" -eq 0 ]; then
  set -- demo
fi

export PYTHONUNBUFFERED=1
# bluetoothd lives in /usr/lib/bluetooth (not on PATH); nuxbt only uses it for -v
export PATH="$VENV/bin:/usr/lib/bluetooth:$PATH"
exec "$NUXBT" "$@"
