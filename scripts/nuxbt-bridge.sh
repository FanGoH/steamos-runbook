#!/usr/bin/env bash
# Launch Sunshine → NUXBT input bridge on the host (USB BT dongle /org/bluez/hci1).
# Requires BlueZ override: sudo -n "$ROOT/scripts/hide-controllers-sysfs.sh" nuxbt-bluez enable
#
# Usage:
#   ./scripts/nuxbt-bridge.sh              # reconnect to last Switch MAC (+ auto-recover)
#   ./scripts/nuxbt-bridge.sh --grip       # Change Grip/Order: advertise + hold L+R
#   touch "$XDG_RUNTIME_DIR/nuxbt-want-grip"      # request advertise while bridge runs
#   touch "$XDG_RUNTIME_DIR/nuxbt-want-reconnect" # request MAC reconnect while running
#   ./scripts/nuxbt-bridge.sh --no-reconnect
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

export NUXBT_ADAPTER="${NUXBT_ADAPTER:-/org/bluez/hci1}"
export NUXBT_SWITCH_MAC="${NUXBT_SWITCH_MAC:-48:F1:EB:C3:F4:85}"
# Controller BD_ADDR (what the Switch pairs to). Locked in ~/.config/nuxbt/controller-mac
# on first run (dongle hardware MAC). Do not randomize — a new MAC forces Grip/Order.
# Override with NUXBT_CONTROLLER_MAC=7C:BB:8A:DE:F0:01 (Nintendo OUI) only when
# deliberately re-pairing; then Grip once and leave it alone.

# USB dongle prep: MT7922 off, power-cycle hci1, Pro Controller name + gamepad CoD.
# Same path Decky QAM Grip/Reconnect uses via nuxbt-api.py.
if [ -x "$CAP_PY" ]; then
  "$CAP_PY" "$ROOT/scripts/nuxbt-prepare-radio.py" 2>/dev/null \
    || echo "warn: radio prepare failed (continuing)"
else
  "$PY" "$ROOT/scripts/nuxbt-prepare-radio.py" 2>/dev/null \
    || echo "warn: radio prepare failed (continuing)"
fi

# Pin / re-apply before create_controller (spoofed MACs die across BlueZ restart).
if [ -x "$CAP_PY" ]; then
  "$CAP_PY" "$ROOT/scripts/nuxbt-pin-controller-mac.py" 2>/dev/null \
    || echo "warn: controller MAC pin failed (continuing with live adapter Address)"
else
  "$PY" "$ROOT/scripts/nuxbt-pin-controller-mac.py" 2>/dev/null \
    || echo "warn: controller MAC pin failed (continuing with live adapter Address)"
fi

# Shared Steam QAM/overlay mute flag ($XDG_RUNTIME_DIR/emupads-mute). The bridge
# also polls gamescope atoms; this watcher is the proven EmuPads path.
"$ROOT/scripts/start-emu-steam-ui-inhibit.sh" >/dev/null 2>&1 || true

exec "$PY" "$ROOT/scripts/nuxbt-sunshine-bridge.py" "$@"
