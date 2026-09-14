#!/usr/bin/env bash
# Let Tender/Steam Play Cemu leave gamescope's 10x10 InputOnly stub.
#
# Holding FOCUSED_APP=769 forever is the spinning logo (wxGTK waits on a
# futex). Tagging the stub as the :0 GAMESCOPECTRL_BASELAYER_WINDOW blacks
# HDMI. Steam RunGame sets :1 FOCUSED_APP but leaves FOCUS_DISPLAY on
# xwayland 0; Cemu lives on :1.
#
# Hammer FOCUSED_APP=<shortcut> and FOCUS_DISPLAY=1, tag STEAM_GAME on the
# Cemu xid, and only switch HDMI to Cemu once the window is a real
# InputOutput surface. Start from host rom-launcher before gtk_init.
# A second start is a no-op unless --force.
set -uo pipefail

APPID="${CEMU_STEAM_APPID:-${SteamAppId:-2374129079}}"
SECONDS_HOLD="${CEMU_FOCUS_SECONDS:-30}"
PIDFILE="${CEMU_FOCUS_PIDFILE:-/home/deck/steamos-playbook/logs/cemu-gamescope-focus.pid}"
LOG="${CEMU_FOCUS_LOG:-/home/deck/steamos-playbook/logs/cemu-gamescope-focus.log}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

mkdir -p "$(dirname "$PIDFILE")" "$(dirname "$LOG")"

kill_old() {
  local old
  old="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "${old:-}" ] && [ -d "/proc/$old" ] && [ "$old" != "$$" ]; then
    kill "$old" 2>/dev/null || true
    pkill -P "$old" 2>/dev/null || true
  fi
  # Leftover from an earlier placeholder experiment.
  for id in $(DISPLAY=:1 xdotool search --name 'cemu-focus-placeholder' 2>/dev/null || true); do
    DISPLAY=:1 xdotool windowkill "$id" 2>/dev/null || true
  done
}

if [ "${1:-}" = "--stop" ]; then
  kill_old
  rm -f "$PIDFILE"
  exit 0
fi

old="$(cat "$PIDFILE" 2>/dev/null || true)"
if [ -n "${old:-}" ] && [ -d "/proc/$old" ] && [ "$old" != "$$" ]; then
  if [ "${1:-}" != "--force" ]; then
    echo "$(date -Iseconds) already running pid=$old appid=$APPID" >>"$LOG"
    exit 0
  fi
  kill_old
  sleep 0.05
fi
printf '%s\n' "$$" >"$PIDFILE"
if [ -x /home/deck/steamos-playbook/scripts/start-emu-steam-ui-inhibit.sh ]; then
  /home/deck/steamos-playbook/scripts/start-emu-steam-ui-inhibit.sh >/dev/null 2>&1 || true
fi

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

set_focus_display() {
  local middle="$1" atom
  for atom in GAMESCOPE_FOCUS_DISPLAY GAMESCOPE_KEYBOARD_FOCUS_DISPLAY GAMESCOPE_MOUSE_FOCUS_DISPLAY; do
    DISPLAY=:0 xprop -root -f "$atom" 32c -set "$atom" "12346, $middle, 66" 2>/dev/null || true
  done
}

set_focused_app() {
  local d
  for d in :0 :1; do
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$APPID" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$APPID" 2>/dev/null || true
  done
}

restore_steam_xwayland() {
  set_focus_display 0
  DISPLAY=:0 xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP 769 2>/dev/null || true
  DISPLAY=:0 xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX 769 2>/dev/null || true
}

hammer_gamescope_focus() {
  local end="$1"
  while [ "$SECONDS" -lt "$end" ]; do
    set_focused_app
    set_focus_display 1
  done
}

prepare_cemu_stub() {
  local d="$1" id name
  [ -S "/tmp/.X11-unix/X${d#:}" ] || return 1
  command -v xdotool >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$d" xdotool search --class Cemu 2>/dev/null || true) \
            $(DISPLAY="$d" xdotool search --name 'Cemu' 2>/dev/null || true); do
    name="$(DISPLAY="$d" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*|*placeholder*) continue ;;
    esac
    DISPLAY="$d" xprop -id "$id" -f STEAM_GAME 32c -set STEAM_GAME "$APPID" 2>/dev/null || true
    DISPLAY="$d" xdotool windowmap "$id" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$id" 2>/dev/null || true
  done
}

promote_real_cemu() {
  local d="$1" id name
  [ -S "/tmp/.X11-unix/X${d#:}" ] || return 1
  command -v xdotool >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$d" xdotool search --class Cemu 2>/dev/null || true) \
            $(DISPLAY="$d" xdotool search --name 'Cemu' 2>/dev/null || true); do
    name="$(DISPLAY="$d" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*|*placeholder*) continue ;;
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
    if [ "$d" = ":1" ]; then
      set_focus_display 1
    else
      set_focus_display 0
    fi
    return 0
  done
  return 1
}

promoted=0
end=$((SECONDS + SECONDS_HOLD))
echo "$(date -Iseconds) FOCUSED_APP=$APPID FOCUS_DISPLAY=1 ${SECONDS_HOLD}s" >>"$LOG"
set_focused_app
set_focus_display 1
hammer_gamescope_focus "$end" &
hammer_pid=$!
trap 'kill "$hammer_pid" 2>/dev/null || true; rm -f "$PIDFILE"' EXIT

while [ "$SECONDS" -lt "$end" ]; do
  if promote_real_cemu :0 || promote_real_cemu :1; then
    echo "$(date -Iseconds) promoted real Cemu window" >>"$LOG"
    promoted=1
    break
  fi
  prepare_cemu_stub :0 || true
  prepare_cemu_stub :1 || true
  sleep 0.05
done

kill "$hammer_pid" 2>/dev/null || true
wait "$hammer_pid" 2>/dev/null || true
if [ "$promoted" -ne 1 ]; then
  restore_steam_xwayland
  echo "$(date -Iseconds) no real Cemu window; restored FOCUS_DISPLAY=0" >>"$LOG"
fi
echo "$(date -Iseconds) done :0=$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}') FOCUS=$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUS_DISPLAY 2>/dev/null | awk -F'= ' '{print $2}') promoted=$promoted" >>"$LOG"
rm -f "$PIDFILE"
trap - EXIT
