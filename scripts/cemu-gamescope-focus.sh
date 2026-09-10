#!/usr/bin/env bash
# Hold gamescope focus on the Steam UI xwayland (:0) so Cemu can leave the
# 10x10 InputOnly stub. HDMI / the Launching spinner follow :0, even when
# the Cemu window lives on :1. Safe to re-run; one instance at a time.
set -uo pipefail

APPID="${CEMU_STEAM_APPID:-${SteamAppId:-2374129079}}"
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

set_atoms() {
  local d="$1"
  DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$APPID" 2>/dev/null || true
  DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$APPID" 2>/dev/null || true
}

# HDMI/spinner follow xwayland 0 (:0). Cemu is on xwayland 1 (:1) and stays
# InputOnly until FOCUS_DISPLAY's middle cardinal is 1.
focus_game_xwayland() {
  local cur a c
  cur="$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUS_DISPLAY 2>/dev/null | awk -F'= ' '{print $2}')"
  a="$(printf '%s' "$cur" | awk -F',' '{gsub(/ /,"",$1); print $1}')"
  c="$(printf '%s' "$cur" | awk -F',' '{gsub(/ /,"",$3); print $3}')"
  [ -n "$a" ] || a=12346
  [ -n "$c" ] || c=66
  local vals="$a, 1, $c"
  for atom in GAMESCOPE_FOCUS_DISPLAY GAMESCOPE_KEYBOARD_FOCUS_DISPLAY GAMESCOPE_MOUSE_FOCUS_DISPLAY; do
    DISPLAY=:0 xprop -root -f "$atom" 32c -set "$atom" "$vals" 2>/dev/null || true
  done
}

tag_windows() {
  local d="$1" id name
  [ -S "/tmp/.X11-unix/X${d#:}" ] || return 0
  command -v xdotool >/dev/null 2>&1 || return 0
  for id in $(DISPLAY="$d" xdotool search --class Cemu 2>/dev/null || true) \
            $(DISPLAY="$d" xdotool search --name 'Cemu' 2>/dev/null || true); do
    name="$(DISPLAY="$d" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*) continue ;;
    esac
    DISPLAY="$d" xprop -id "$id" -f STEAM_GAME 32c -set STEAM_GAME "$APPID" 2>/dev/null || true
    DISPLAY="$d" xdotool windowmap "$id" 2>/dev/null || true
    if [ "$d" = ":0" ]; then
      DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$id" 2>/dev/null || true
      DISPLAY="$d" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$id" 2>/dev/null || true
    fi
  done
}

end=$((SECONDS + SECONDS_HOLD))
echo "$(date -Iseconds) hold appid=$APPID ${SECONDS_HOLD}s interval=${INTERVAL_MS}ms" >>"$LOG"
while [ "$SECONDS" -lt "$end" ]; do
  # Spinner / HDMI follow :0. :1 is the game xwayland Cemu actually uses.
  set_atoms :0
  set_atoms :1
  focus_game_xwayland
  tag_windows :0
  tag_windows :1
  sleep "$(awk -v ms="$INTERVAL_MS" 'BEGIN { printf "%.3f", ms/1000 }')"
done
echo "$(date -Iseconds) done :0=$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}')" >>"$LOG"
rm -f "$PIDFILE"
