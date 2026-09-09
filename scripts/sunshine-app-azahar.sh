#!/usr/bin/env bash
# Sunshine-ds Moonlight app: pick a 3DS dump immediately, bind the GameStream
# pad, launch standalone Azahar with Separate Windows (top HDMI, bottom
# Virtual-sunshine-ds), then wait until Azahar exits so the session stays BUSY.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/sunshine-app-common.sh
source "$ROOT/scripts/sunshine-app-common.sh"
reexec_on_host "$ROOT/scripts/sunshine-app-azahar.sh"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export AZAHAR_ALLOW_LIBRARY="${AZAHAR_ALLOW_LIBRARY:-1}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export DISPLAY="${DISPLAY:-:0}"
mkdir -p "$ROOT/logs"

picker_pid=""
place_watch_pid=""
prep_pid=""

cleanup() {
  echo "Moonlight stopped the app; closing matching processes."
  [ -n "$picker_pid" ] && kill "$picker_pid" 2>/dev/null || true
  [ -n "$place_watch_pid" ] && kill "$place_watch_pid" 2>/dev/null || true
  [ -n "$prep_pid" ] && kill "$prep_pid" 2>/dev/null || true
  stop_azahar_picker
  stop_matching_comm '^azahar'
  trap - INT TERM
  exit 0
}
trap cleanup INT TERM

# Leftover Azahar covers the picker and makes Open look like a no-op.
if ps -eo comm= | grep -Eq '^azahar'; then
  echo "Stopping leftover Azahar so this Moonlight app can boot."
  stop_matching_comm '^azahar'
fi

# Ini + bind while the list is on screen. Do not wait on a Sunshine pad first.
bash "$ROOT/scripts/ensure-azahar-dual-screen.sh" --prep-only \
  >>"$ROOT/logs/sunshine-app-azahar.log" 2>&1 &
prep_pid=$!

if [ -z "${AZAHAR_ROM:-}" ]; then
  pick_file="${XDG_RUNTIME_DIR:-/tmp}/azahar-pick.$$"
  rm -f "$pick_file"
  echo "Showing Azahar game list on HDMI."
  python3 "$ROOT/scripts/azahar-game-picker.py" >"$pick_file" 2>>"$ROOT/logs/sunshine-app-azahar.log" &
  picker_pid=$!
  wait "$picker_pid"
  pick_rc=$?
  picker_pid=""
  picked=""
  if [ -s "$pick_file" ]; then
    picked="$(head -n 1 "$pick_file")"
  fi
  rm -f "$pick_file"
  if [ "$pick_rc" -eq 0 ] && [ -n "$picked" ] && [ -f "$picked" ]; then
    export AZAHAR_ROM="$picked"
    export AZAHAR_ALLOW_LIBRARY=0
    echo "Azahar ROM: $AZAHAR_ROM"
  elif [ "$pick_rc" -eq 2 ]; then
    echo "Game list cancelled; opening the Azahar library."
  else
    echo "Game list unavailable (rc=$pick_rc); opening the Azahar library."
  fi
fi

wait "$prep_pid" 2>/dev/null || true
prep_pid=""

if ! bash "$ROOT/scripts/ensure-azahar-dual-screen.sh"; then
  echo "ensure-azahar-dual-screen.sh failed. See $ROOT/logs/azahar-dual-screen.log and $ROOT/logs/manual-actions*.txt"
  exit 1
fi

# ROM / library windows can appear after the first place. Re-place until exit.
(
  while ps -eo comm= | grep -Eq '^azahar'; do
    bash "$ROOT/scripts/ensure-azahar-dual-screen.sh" --place-only >/dev/null 2>&1 || true
    sleep 1
  done
) &
place_watch_pid=$!

echo "Azahar dual-screen is up; waiting until Azahar exits."
wait_while_comm '^azahar' "$place_watch_pid"
echo "Azahar exited."
exit 0
