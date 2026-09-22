#!/usr/bin/env bash
# Run NUXBT on the HOST (not Distrobox).
# SteamOS /usr/bin/python3 has AF_BLUETOOTH; Distrobox cannot raw-HCI set_class
# (PermissionError) so Switch never sees CoD 0x002508.
# File caps live on ~/code/nuxbt-host/bin/python3-nuxbt (not /usr — immutable).
#
# Verbose by default (-d + logfile). Quiet: NUXBT_QUIET=1 ~/…/nuxbt-run.sh demo
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_HOST_DIR:-/home/${STEAMOS_USER}/code/nuxbt-host}"
VENV="$DIR/.venv"
NUXBT="$VENV/bin/nuxbt"
CAP_PY="${NUXBT_PYTHON:-$DIR/bin/python3-nuxbt}"
LOG_DIR="${NUXBT_LOG_DIR:-$ROOT/logs}"
LOG_FILE="${NUXBT_LOG:-$LOG_DIR/nuxbt-$(date +%Y%m%d-%H%M%S).log}"
QUIET="${NUXBT_QUIET:-0}"

# Pro Controller CoD. Setting Discoverable can reset Class to 0x400000 — re-assert.
COD_HEX=002508

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

mkdir -p "$LOG_DIR"

# Pin discoverable forever before NUXBT (stock nuxbt used 180s — Grip/Order died mid-demo).
# Also re-apply after; toggling Discoverable resets Class on BlueZ 5.87 / MT7922.
pin_bt_visibility() {
  "$CAP_PY" - <<'PY' 2>/dev/null || true
import dbus
bus = dbus.SystemBus()
obj = bus.get_object("org.bluez", "/org/bluez/hci0")
p = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
iface = "org.bluez.Adapter1"
p.Set(iface, "DiscoverableTimeout", dbus.UInt32(0))
p.Set(iface, "PairableTimeout", dbus.UInt32(0))
p.Set(iface, "Pairable", dbus.Boolean(True))
p.Set(iface, "Discoverable", dbus.Boolean(True))
print("dbus: DiscoverableTimeout=0 Discoverable=on")
PY
}

write_cod() {
  "$CAP_PY" - <<PY 2>/dev/null || true
import socket, struct
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
s.bind((0,))
# HCI Write Class of Device → 0x${COD_HEX}
pkt = struct.pack("<BHB", 0x01, 0x0c24, 3) + bytes.fromhex("${COD_HEX}")[::-1]
s.send(pkt)
s.close()
print("hci: class 0x${COD_HEX}")
PY
}

current_cod() {
  bluetoothctl show 2>/dev/null | awk '/Class:/{print $2; exit}'
}

# Preflight snapshot (also mirrored into the log file)
{
  echo "=== nuxbt-run preflight $(date -Is) ==="
  echo "cmd: $NUXBT $*"
  echo "python: $(readlink -f "$VENV/bin/python3" 2>/dev/null || true)"
  echo "caps: $(getcap "$CAP_PY" 2>/dev/null || echo none)"
  echo "bluetoothd: $(ps -o args= -C bluetoothd 2>/dev/null || echo '(not running)')"
  echo "bluetoothd -v: $(bluetoothd -v 2>/dev/null || echo '(not on PATH yet)')"
  if command -v hciconfig >/dev/null 2>&1; then
    hciconfig hci0 2>/dev/null | sed 's/^/hci0: /' || echo "hci0: (unavailable)"
  fi
  if command -v bluetoothctl >/dev/null 2>&1; then
    bluetoothctl show 2>/dev/null | grep -E 'Name:|Alias:|Class:|Powered:|Discoverable:|Pairable:' \
      | sed 's/^/bt: /' || true
  fi
  echo "log: $LOG_FILE"
  echo "quiet: $QUIET"
  echo "========================================"
} | tee -a "$LOG_FILE"

pin_bt_visibility | tee -a "$LOG_FILE"
write_cod | tee -a "$LOG_FILE"

export PYTHONUNBUFFERED=1
# bluetoothd lives in /usr/lib/bluetooth (not on PATH); nuxbt only uses it for -v
export PATH="$VENV/bin:/usr/lib/bluetooth:$PATH"

NUXBT_OPTS=()
if [ "$QUIET" != "1" ]; then
  NUXBT_OPTS+=(-d --logfile "$LOG_FILE")
  echo "NUXBT debug on → stderr + $LOG_FILE"
fi

# Side channel: CoD/ACL + re-assert CoD if BlueZ resets it (discoverable toggle)
(
  for _ in $(seq 1 180); do
    {
      echo "--- monitor $(date -Is) ---"
      hciconfig hci0 2>/dev/null | grep -E 'BD Address|RX bytes|TX bytes|Class:' || true
      bluetoothctl show 2>/dev/null | grep -E 'Alias:|Class:|Discoverable:|Pairable:|DiscoverableTimeout:' || true
      cod="$(current_cod || true)"
      if [ -n "$cod" ] && [ "$cod" != "0x00002508" ] && [ "$cod" != "0x002508" ]; then
        echo "warn: Class drifted to $cod — rewriting 0x${COD_HEX}"
        write_cod
        pin_bt_visibility
      fi
    } >>"$LOG_FILE"
    sleep 2
  done
) &
MON_PID=$!
trap 'kill "$MON_PID" 2>/dev/null || true' EXIT

# Click global opts must precede the subcommand: nuxbt -d --logfile … demo
set +e
"$NUXBT" "${NUXBT_OPTS[@]}" "$@"
rc=$?
set -e
kill "$MON_PID" 2>/dev/null || true
wait "$MON_PID" 2>/dev/null || true
trap - EXIT
{
  echo "=== nuxbt-run exit rc=$rc $(date -Is) ==="
  hciconfig hci0 2>/dev/null | grep -E 'BD Address|RX bytes|TX bytes|Class:' || true
  bluetoothctl show 2>/dev/null | grep -E 'Alias:|Class:|Discoverable:|Pairable:' || true
} | tee -a "$LOG_FILE"
exit "$rc"
