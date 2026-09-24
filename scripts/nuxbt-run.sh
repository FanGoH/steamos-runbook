#!/usr/bin/env bash
# Run NUXBT on the HOST (not Distrobox).
# SteamOS /usr is immutable — file caps live on ~/code/nuxbt-host/bin/python3-nuxbt.
# Verbose by default (-d + logfile). Quiet: NUXBT_QUIET=1 ~/…/nuxbt-run.sh demo
set -uo pipefail

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
COD_HEX=002508
MON_PID=""
RC=130

if [ ! -x "$NUXBT" ]; then
  echo "Host NUXBT missing. Run: $ROOT/scripts/ensure-nuxbt.sh"
  exit 1
fi

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ]; then
  echo "Host BlueZ override not enabled."
  echo "Run: sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
  exit 2
fi

if [ ! -x "$CAP_PY" ] || ! getcap "$CAP_PY" 2>/dev/null | grep -q cap_net_raw; then
  echo "warn: $CAP_PY lacks cap_net_raw — Switch may ignore wrong CoD."
  echo "      sudo $ROOT/scripts/nuxbt-bluez-override.sh enable"
fi

if [ "$#" -eq 0 ]; then
  set -- demo
fi

mkdir -p "$LOG_DIR"

log() {
  # Avoid `{ … } | tee` after Ctrl-C (can confuse the parser mid-interrupt).
  printf '%s\n' "$*" | tee -a "$LOG_FILE" >/dev/null
  printf '%s\n' "$*"
}

pin_bt_visibility() {
  "$CAP_PY" - <<'PY' >>"$LOG_FILE" 2>/dev/null || true
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
  "$CAP_PY" - <<PY >>"$LOG_FILE" 2>/dev/null || true
import socket, struct
s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
s.bind((0,))
pkt = struct.pack("<BHB", 0x01, 0x0c24, 3) + bytes.fromhex("${COD_HEX}")[::-1]
s.send(pkt)
s.close()
print("hci: class 0x${COD_HEX}")
PY
}

current_cod() {
  bluetoothctl show 2>/dev/null | awk '/Class:/{print $2; exit}'
}

cleanup() {
  if [ -n "${MON_PID}" ] && kill -0 "$MON_PID" 2>/dev/null; then
    kill "$MON_PID" 2>/dev/null || true
    wait "$MON_PID" 2>/dev/null || true
  fi
  echo "=== nuxbt-run exit rc=${RC} $(date -Is) ===" | tee -a "$LOG_FILE"
  hciconfig hci0 2>/dev/null | grep -E 'BD Address|RX bytes|TX bytes|Class:' | tee -a "$LOG_FILE" || true
  bluetoothctl show 2>/dev/null | grep -E 'Alias:|Class:|Discoverable:|Pairable:' | tee -a "$LOG_FILE" || true
}
trap cleanup EXIT
trap 'RC=130; exit 130' INT TERM

log "=== nuxbt-run preflight $(date -Is) ==="
log "cmd: $NUXBT $*"
log "python: $(readlink -f "$VENV/bin/python3" 2>/dev/null || true)"
log "caps: $(getcap "$CAP_PY" 2>/dev/null || echo none)"
log "bluetoothd: $(ps -o args= -C bluetoothd 2>/dev/null || echo '(not running)')"
log "bluetoothd -v: $(PATH="/usr/lib/bluetooth:$PATH" bluetoothd -v 2>/dev/null || echo missing)"
hciconfig hci0 2>/dev/null | sed 's/^/hci0: /' | tee -a "$LOG_FILE" || log "hci0: (unavailable)"
bluetoothctl show 2>/dev/null | grep -E 'Name:|Alias:|Class:|Powered:|Discoverable:|Pairable:' \
  | sed 's/^/bt: /' | tee -a "$LOG_FILE" || true
log "log: $LOG_FILE"
log "quiet: $QUIET"
log "========================================"

pin_bt_visibility
write_cod
# Mirror last lines of those helpers to stdout
tail -n 2 "$LOG_FILE" | grep -E 'dbus:|hci: class' || true

export PYTHONUNBUFFERED=1
export PATH="$VENV/bin:/usr/lib/bluetooth:$PATH"

NUXBT_OPTS=()
if [ "$QUIET" != "1" ]; then
  NUXBT_OPTS+=(-d --logfile "$LOG_FILE")
  log "NUXBT debug on → stderr + $LOG_FILE"
fi

# CoD/ACL monitor; re-assert CoD if BlueZ resets it after Discoverable toggles
(
  for _ in $(seq 1 180); do
    {
      echo "--- monitor $(date -Is) ---"
      hciconfig hci0 2>/dev/null | grep -E 'BD Address|RX bytes|TX bytes|Class:' || true
      bluetoothctl show 2>/dev/null | grep -E 'Alias:|Class:|Discoverable:|Pairable:|DiscoverableTimeout:' || true
      cod="$(bluetoothctl show 2>/dev/null | awk '/Class:/{print $2; exit}')"
      if [ -n "$cod" ] && [ "$cod" != "0x00002508" ] && [ "$cod" != "0x002508" ]; then
        echo "warn: Class drifted to $cod — rewriting 0x${COD_HEX}"
      fi
    } >>"$LOG_FILE" 2>/dev/null
    # Re-assert outside the brace so heredocs are not nested under a redirected group
    cod="$(bluetoothctl show 2>/dev/null | awk '/Class:/{print $2; exit}')"
    if [ -n "$cod" ] && [ "$cod" != "0x00002508" ] && [ "$cod" != "0x002508" ]; then
      write_cod
      pin_bt_visibility
    fi
    sleep 2
  done
) &
MON_PID=$!

"$NUXBT" "${NUXBT_OPTS[@]}" "$@"
RC=$?
exit "$RC"
