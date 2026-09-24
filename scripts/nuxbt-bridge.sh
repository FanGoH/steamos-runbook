#!/usr/bin/env bash
# Launch Sunshine → NUXBT input bridge on the host (USB BT dongle /org/bluez/hci1).
# Requires BlueZ override: sudo -n "$ROOT/scripts/hide-controllers-sysfs.sh" nuxbt-bluez enable
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_HOST_DIR:-/home/${STEAMOS_USER}/code/nuxbt-host}"
VENV="$DIR/.venv"
PY="$VENV/bin/python"
CAP_PY="${NUXBT_PYTHON:-$DIR/bin/python3-nuxbt}"

if [ ! -x "$PY" ]; then
  echo "Host NUXBT missing. Run: $ROOT/scripts/ensure-nuxbt.sh"
  exit 1
fi

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ]; then
  echo "BlueZ override absent. Enabling via NOPASSWD helper…"
  sudo -n "$ROOT/scripts/hide-controllers-sysfs.sh" nuxbt-bluez enable \
    || { echo "Run: sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"; exit 2; }
fi

if [ ! -x "$CAP_PY" ] || ! getcap "$CAP_PY" 2>/dev/null | grep -q cap_net_raw; then
  echo "warn: $CAP_PY lacks cap_net_raw — Switch may ignore wrong CoD."
fi

# Keep MT7922 down when USB dongle is the NUXBT radio
"$CAP_PY" - <<'PY' 2>/dev/null || true
import dbus
bus = dbus.SystemBus()
for path, on in (("/org/bluez/hci0", False), ("/org/bluez/hci1", True)):
    try:
        p = dbus.Interface(bus.get_object("org.bluez", path), "org.freedesktop.DBus.Properties")
        p.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(on))
    except Exception:
        pass
PY

export NUXBT_ADAPTER="${NUXBT_ADAPTER:-/org/bluez/hci1}"
export NUXBT_SWITCH_MAC="${NUXBT_SWITCH_MAC:-48:F1:EB:C3:F4:85}"

exec "$PY" "$ROOT/scripts/nuxbt-sunshine-bridge.py" "$@"
