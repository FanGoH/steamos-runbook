#!/usr/bin/env bash
# Run NUXBT against the host BlueZ stack from Distrobox steamos-tools.
# Distrobox does not mount /run/dbus; host /run is at /run/host/run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_DIR:-/home/${STEAMOS_USER}/code/nuxbt}"
CONTAINER="${NUXBT_DISTROBOX:-steamos-tools}"
VENV="$DIR/.venv"

if [ ! -x "$VENV/bin/nuxbt" ]; then
  echo "NUXBT missing. Run: $ROOT/scripts/ensure-nuxbt.sh"
  exit 1
fi

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ]; then
  echo "Host BlueZ override not enabled."
  echo "Run: sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
  exit 2
fi

if [ "$#" -eq 0 ]; then
  set -- demo
fi

args_q=
for a in "$@"; do
  args_q+=" $(printf '%q' "$a")"
done

exec distrobox enter "$CONTAINER" -- bash -lc "
set -e
export PATH=$(printf '%q' "$VENV/bin"):\"\$HOME/.local/bin:\$PATH\"
export DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/host/run/dbus/system_bus_socket
mkdir -p \"\$HOME/.local/bin\"
if [ ! -x \"\$HOME/.local/bin/bluetoothd\" ]; then
  if [ -x /usr/libexec/bluetooth/bluetoothd ]; then
    ln -sfn /usr/libexec/bluetooth/bluetoothd \"\$HOME/.local/bin/bluetoothd\"
  elif [ -x /run/host/usr/lib/bluetooth/bluetoothd ]; then
    ln -sfn /run/host/usr/lib/bluetooth/bluetoothd \"\$HOME/.local/bin/bluetoothd\"
  fi
fi
exec nuxbt${args_q}
"
