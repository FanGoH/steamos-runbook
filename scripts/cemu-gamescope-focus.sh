#!/usr/bin/env bash
# Let Tender/Steam Play Cemu leave gamescope's 10x10 InputOnly stub.
#
# gamescope keeps an unfocused client as InputOnly (no /dev/dri, no Init Cemu)
# until all three are true:
#   1. GAMESCOPE_FOCUSED_APP = shortcut AppId (not Steam 769)
#   2. the Cemu window has STEAM_GAME = that AppId
#   3. GAMESCOPE_FOCUS_DISPLAY's middle cardinal is 1 (Cemu lives on :1)
#
# Holding 769 forever leaves wxGTK on a futex (spinning logo). Setting
# GAMESCOPECTRL_BASELAYER_WINDOW to the stub makes HDMI an empty surface
# (black instead of Launching). Tag STEAM_GAME on the stub, move focus to
# xwayland 1, keep Steam BPM as the :0 baselayer, and only switch HDMI to
# Cemu once the window is a real InputOutput surface.
#
# Start this from host rom-launcher *before* RetroDECK/gtk_init. Safe to
# re-run; one instance at a time. A second start is a no-op unless --force.
set -uo pipefail

APPID="${CEMU_STEAM_APPID:-${SteamAppId:-2374129079}}"
STEAM_CLIENT_ID="${CEMU_STEAM_CLIENT_ID:-769}"
SECONDS_HOLD="${CEMU_FOCUS_SECONDS:-30}"
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
  if [ "${1:-}" != "--force" ]; then
    echo "$(date -Iseconds) already running pid=$old appid=$APPID" >>"$LOG"
    exit 0
  fi
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

steam_bpm_dec() {
  local bpm
  bpm="$(DISPLAY=:0 xwininfo -root -tree 2>/dev/null | awk '/"Steam Big Picture Mode"/{print $1; exit}')"
  [ -n "${bpm:-}" ] || return 1
  printf '%d' "$bpm" 2>/dev/null || printf '%s' "$bpm"
}

keep_hdmi_logo_baselayer() {
  local bpm_dec
  bpm_dec="$(steam_bpm_dec || true)"
  if [ -n "${bpm_dec:-}" ]; then
    DISPLAY=:0 xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$bpm_dec" 2>/dev/null || true
    DISPLAY=:0 xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$bpm_dec" 2>/dev/null || true
  fi
}

set_focus_display() {
  local middle="$1" cur a c vals atom
  cur="$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUS_DISPLAY 2>/dev/null | awk -F'= ' '{print $2}')"
  a="$(printf '%s' "$cur" | awk -F',' '{gsub(/ /,"",$1); print $1}')"
  c="$(printf '%s' "$cur" | awk -F',' '{gsub(/ /,"",$3); print $3}')"
  [ -n "$a" ] || a=12346
  [ -n "$c" ] || c=66
  vals="$a, $middle, $c"
  for atom in GAMESCOPE_FOCUS_DISPLAY GAMESCOPE_KEYBOARD_FOCUS_DISPLAY GAMESCOPE_MOUSE_FOCUS_DISPLAY; do
    DISPLAY=:0 xprop -root -f "$atom" 32c -set "$atom" "$vals" 2>/dev/null || true
  done
}

give_cemu_app_focus() {
  local d
  for d in :0 :1; do
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$APPID" 2>/dev/null || true
    DISPLAY="$d" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$APPID" 2>/dev/null || true
  done
  # Cemu's window is on xwayland 1. It stays InputOnly until this middle
  # cardinal is 1. HDMI follows it — keep :0 BASELAYER on Steam BPM so a
  # still-empty stub is not the nested surface gamescope presents.
  set_focus_display 1
  keep_hdmi_logo_baselayer
}

prepare_cemu_stub() {
  local d="$1" id name tagged=0
  [ -S "/tmp/.X11-unix/X${d#:}" ] || return 1
  command -v xdotool >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$d" xdotool search --class Cemu 2>/dev/null || true) \
            $(DISPLAY="$d" xdotool search --name 'Cemu' 2>/dev/null || true); do
    name="$(DISPLAY="$d" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*) continue ;;
    esac
    DISPLAY="$d" xprop -id "$id" -f STEAM_GAME 32c -set STEAM_GAME "$APPID" 2>/dev/null || true
    DISPLAY="$d" xdotool windowmap "$id" 2>/dev/null || true
    tagged=1
  done
  [ "$tagged" -eq 1 ]
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
    # :0 and :1 are different X servers. Never copy a :1 xid onto :0.
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
echo "$(date -Iseconds) FOCUSED_APP=$APPID STEAM_GAME on stub FOCUS_DISPLAY=1 ${SECONDS_HOLD}s" >>"$LOG"
give_cemu_app_focus
while [ "$SECONDS" -lt "$end" ]; do
  if promote_real_cemu :0 || promote_real_cemu :1; then
    echo "$(date -Iseconds) promoted real Cemu window" >>"$LOG"
    promoted=1
    break
  fi
  prepare_cemu_stub :0 || true
  prepare_cemu_stub :1 || true
  give_cemu_app_focus
  sleep "$(awk -v ms="$INTERVAL_MS" 'BEGIN { printf "%.3f", ms/1000 }')"
done
if [ "$promoted" -ne 1 ]; then
  # Failed boot: put HDMI back on Steam UI xwayland so the stream is not
  # stuck on an empty :1 stub.
  set_focus_display 0
  keep_hdmi_logo_baselayer
  echo "$(date -Iseconds) no real Cemu window; restored FOCUS_DISPLAY=0" >>"$LOG"
fi
echo "$(date -Iseconds) done :0=$(DISPLAY=:0 xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}') promoted=$promoted" >>"$LOG"
rm -f "$PIDFILE"
