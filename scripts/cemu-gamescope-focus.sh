#!/usr/bin/env bash
# Keep HDMI on Steam's Launching / Big Picture until Cemu has a real window.
# Tagging the 10x10 InputOnly stub STEAM_GAME makes gamescope present that
# empty surface — black instead of the stream logo. Safe to re-run; one
# instance at a time.
set -uo pipefail

APPID="${CEMU_STEAM_APPID:-${SteamAppId:-2374129079}}"
STEAM_CLIENT_ID="${CEMU_STEAM_CLIENT_ID:-769}"
SECONDS_HOLD="${CEMU_FOCUS_SECONDS:-20}"
INTERVAL_MS="${CEMU_FOCUS_INTERVAL_MS:-20}"
PIDFILE="${CEMU_FOCUS_PIDFILE:-/home/deck/steamos-playbook/logs/cemu-gamescope-focus.pid}"
LOG="${CEMU_FOCUS_LOG:-/home/deck/steamos-playbook/logs/cemu-gamescope-focus.log}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

mkdir -p "$(dirname "$PIDFILE")" "$(dirname "$LOG")"

if [ "${1:-}" = "--stop" ]; then
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "${old:-}" ] && [ -d "/proc/$old" ]; then
    kill "$old" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  exit 0
fi

old="$(cat "$PIDFILE" 2>/dev/null || true)"
if [ -n "${old:-}" ] && [ -d "/proc/$old" ] && [ "$old" != "$$" ]; then
  kill "$old" 2>/dev/null || true
  sleep 0.05
fi
printf '%s\n' "$$" >"$PIDFILE"

cemu_window_is_stub() {
  local d="$1" id="$2" w h cls
  w="$(DISPLAY="$d" xwininfo -id "$id" 2>/dev/null | awk '/^  Width:/{print $2; exit}')"
  h="$(DISPLAY="$d" xwininfo -id "$id" 2>/dev/null | awk '/^  Height:/{print $2; exit}')"
  cls="$(DISPLAY="$d" xwininfo -id "$id" 2>/dev/null | awk '/^  Class:/{print $2; exit}')"
  if [ "${cls:-}" = "InputOnly" ]; then
    return 0
  fi
  [ -n "${w:-}" ] && [ -n "${h:-}" ] || return 0
  [ "$w" -lt 64 ] || [ "$h" -lt 64 ]
}

hold_steam_launch_logo() {
  local bpm bpm_dec
  bpm="$(DISPLAY=:0 xwininfo -root -tree 2>/dev/null | awk '/"Steam Big Picture Mode"/{print $1; exit}')"
  DISPLAY=:0 xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
  DISPLAY=:0 xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$STEAM_CLIENT_ID" 2>/dev/null || true
  DISPLAY=:1 xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
  DISPLAY=:1 xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$STEAM_CLIENT_ID" 2>/dev/null || true
  if [ -n "${bpm:-}" ]; then
    bpm_dec="$(printf '%d' "$bpm" 2>/dev/null || printf '%s' "$bpm")"
    DISPLAY=:0 xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$bpm_dec" 2>/dev/null || true
    DISPLAY=:0 xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$bpm_dec" 2>/dev/null || true
  fi
}

promote_real_cemu() {
  local d="$1" id name
  [ -S "/tmp/.X11-unix/X${d#:}" ] || return 1
  command -v xdotool >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$d" xdotool search --class Cemu 2>/dev/null || true) \
            $(DISPLAY="$d" xdotool search --name 'Cemu' 2>/dev/null || true); do
    name="$(DISPLAY="$d" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*) continue ;;
    esac
    if cemu_window_is_stub "$d" "$id"; then
      continue
    fi
    DISPLAY="$d" xprop -id "$id" -f STEAM_GAME 32c -set STEAM_GAME "$APPID" 2>/dev/null || true
    DISPLAY="$d" xdotool windowmap "$id" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$id" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$APPID" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$APPID" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$id" 2>/dev/null || true
    return 0
  done
  return 1
}

end=$((SECONDS + SECONDS_HOLD))
echo "$(date -Iseconds) hold steam logo until real Cemu window appid=$APPID ${SECONDS_HOLD}s" >>"$LOG"
while [ "$SECONDS" -lt "$end" ]; do
  if promote_real_cemu :0 || promote_real_cemu :1; then
    echo "$(date -Iseconds) promoted real Cemu window" >>"$LOG"
    break
  fi
  hold_steam_launch_logo
  sleep "$(awk -v ms="$INTERVAL_MS" 'BEGIN { printf "%.3f", ms/1000 }')"
done
echo "$(date -Iseconds) done :0=$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}')" >>"$LOG"
rm -f "$PIDFILE"
