#!/usr/bin/env bash
# Game Mode (:48200) Cemu dual-stream: TV on session gamescope HDMI, GamePad
# View mirrored onto the headless gamescope DISPLAY=:2 PipeWire node.
#
# Steam overlay: reaper SteamLaunch with the Wind Waker HD shortcut AppId,
# then the same RetroDECK Cemu command as that tile — with CEMU_GAMEMODE_DS=1
# so the wrapper does not force -f. Does not rewrite shortcuts.vdf.
# HDMI is gamescope's focused surface, not X11 stacking. Tag the Cemu TV
# window STEAM_GAME and set GAMESCOPECTRL_BASELAYER_WINDOW or Steam BPM
# stays on video/0 while GamePad View still mirrors. GamePad stays mapped
# on-screen under the TV; ffplay x11grab -window_id copies that drawable
# onto :2. Off-screen ximagesrc is MIT-SHM BadMatch.
#
# Does not touch sunshine-ds-dev (:48100), Decky, or gamescope-session.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
LOG="${ROOT}/logs/cemu-gamemode-ds.log"
MIRROR_PIDFILE="${ROOT}/logs/cemu-gamemode-pad-mirror.pid"
FOCUS_PIDFILE="${ROOT}/logs/cemu-gamemode-focus.pid"
PAINT_PIDFILE="${SUNSHINE_DS_KMS_VIRTUAL_PAINT_PIDFILE:-$ROOT/logs/sunshine-ds-gamemode-virtual-paint.pid}"
STEAM_CLIENT_ID=769
RD_SETTINGS="${CEMU_RD_SETTINGS:-/home/${STEAMOS_USER:-deck}/.var/app/net.retrodeck.retrodeck/config/Cemu/settings.xml}"
RD_CONTROLLER="${CEMU_RD_CONTROLLER:-/home/${STEAMOS_USER:-deck}/.var/app/net.retrodeck.retrodeck/config/Cemu/controllerProfiles/controller0.xml}"
ROM="${CEMU_ROM:-/home/${STEAMOS_USER:-deck}/retrodeck/roms/wiiu/Legend of Zelda, The - The Wind Waker HD (USA, Asia) (En,Fr,Es).wux}"
APPID="${CEMU_STEAM_APPID:-2374129079}"
PAD_MATCH="${CEMU_PAD_MATCH:-Sunshine}"
# Skip the Eden pad patcher in ensure-cemu-input.sh (Steam virtual first).
export CEMU_GAMEMODE_DS=1
TV_DISPLAY="${CEMU_TV_DISPLAY:-:0}"
PAD_DISPLAY="${CEMU_PAD_DISPLAY:-:2}"
REAPER="${STEAM_REAPER:-/home/${STEAMOS_USER:-deck}/.local/share/Steam/ubuntu12_32/reaper}"
VIRTUAL_HELPER="${ROOT}/scripts/sunshine-ds-gamemode-virtual.sh"

mkdir -p "$ROOT/logs"
: >>"$LOG"

usage() {
  sed -n '2,12p' "$0"
}

DO_STOP=0
for arg in "$@"; do
  case "$arg" in
    --stop) DO_STOP=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "usage: $0 [--stop]" >&2
      exit 2
      ;;
  esac
done

cemu_running() {
  ps -eo comm= | grep -Eq '^[Cc]emu'
}

stop_paint() {
  local pid
  pid="$(cat "$PAINT_PIDFILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ]; then
    echo "Stopping virtual paint pid $pid."
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$PAINT_PIDFILE"
  # Leftover Tk stays mapped after the python pid dies and covers :2.
  DISPLAY="$PAD_DISPLAY" xdotool search --name 'sunshine-ds-kms-virtual' windowkill 2>/dev/null || true
}

stop_mirror() {
  local pid
  pid="$(cat "$MIRROR_PIDFILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ]; then
    echo "Stopping GamePad mirror pid $pid."
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$MIRROR_PIDFILE"
}

stop_focus_watch() {
  local pid
  pid="$(cat "$FOCUS_PIDFILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ]; then
    echo "Stopping Cemu gamescope focus pid $pid."
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$FOCUS_PIDFILE"
}

write_rd_geometry() {
  python3 - "$RD_SETTINGS" <<'PY'
import sys, xml.etree.ElementTree as ET
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    sys.stderr.write("Missing %s\n" % path)
    sys.exit(1)

def set_xy(parent, tag, x, y):
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    for name, val in (("x", str(x)), ("y", str(y))):
        child = node.find(name)
        if child is None:
            child = ET.SubElement(node, name)
        child.text = val

tree = ET.parse(path)
root = tree.getroot()
for tag, val in (("fullscreen", "false"), ("open_pad", "true")):
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    node.text = val
set_xy(root, "window_position", 0, 0)
set_xy(root, "window_size", 1920, 1080)
# Off-screen pad (1920,0) cannot be x11grab'd (MIT-SHM BadMatch). Keep it
# mapped on-screen under the TV; window_id grab still sees GamePad pixels.
set_xy(root, "pad_position", 0, 0)
set_xy(root, "pad_size", 1920, 1080)
tree.write(path, encoding="UTF-8", xml_declaration=True)
print("Wrote RetroDECK Cemu TV/pad geometry in", path)
PY
}

find_pad_wid() {
  # Off-screen GamePad (1920,0 on a 1920-wide :0) is mapped but not "visible".
  DISPLAY="$TV_DISPLAY" xdotool search --name 'GamePad' 2>/dev/null | head -1
}

wait_cemu() {
  local i=0
  while [ "$i" -lt 45 ]; do
    if cemu_running; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

ensure_virtual_display() {
  if DISPLAY="$PAD_DISPLAY" xdpyinfo >/dev/null 2>&1; then
    return 0
  fi
  echo "Headless gamescope $PAD_DISPLAY is down; starting virtual helper."
  bash "$VIRTUAL_HELPER" --start
}

wait_pad_wid() {
  local i=0 wid
  while [ "$i" -lt 90 ]; do
    wid="$(find_pad_wid || true)"
    if [ -n "${wid:-}" ]; then
      printf '%s\n' "$wid"
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

place_pad_for_capture() {
  local wid="$1"
  DISPLAY="$TV_DISPLAY" xdotool windowmap "$wid" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowsize "$wid" 1920 1080 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowmove "$wid" 0 0 2>/dev/null || true
  present_cemu_tv || true
}

find_tv_wid() {
  local id name
  for id in $(DISPLAY="$TV_DISPLAY" xdotool search --name 'Cemu 2.6' 2>/dev/null || true); do
    name="$(DISPLAY="$TV_DISPLAY" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*) continue ;;
      Cemu\ 2.6*)
        printf '%s\n' "$id"
        return 0
        ;;
    esac
  done
  for id in $(DISPLAY="$TV_DISPLAY" xdotool search --name 'Cemu' 2>/dev/null || true); do
    name="$(DISPLAY="$TV_DISPLAY" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      GamePad*|Cemu_relwithdebinfo) continue ;;
      Cemu*)
        printf '%s\n' "$id"
        return 0
        ;;
    esac
  done
  return 1
}

steam_overlay_active() {
  local wid val
  command -v xdotool >/dev/null 2>&1 || return 1
  command -v xprop >/dev/null 2>&1 || return 1
  for wid in $(DISPLAY="$TV_DISPLAY" xdotool search --class steam 2>/dev/null || true) \
             $(DISPLAY="$TV_DISPLAY" xdotool search --class steamwebhelper 2>/dev/null || true); do
    val="$(DISPLAY="$TV_DISPLAY" xprop -id "$wid" STEAM_OVERLAY 2>/dev/null | awk -F'= ' '{print $2}')"
    if [ "${val:-0}" = "1" ]; then
      return 0
    fi
  done
  return 1
}

set_gamescope_focus() {
  local id="$1" app="$2"
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$id" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$app" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$app" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$id" 2>/dev/null || true
}

present_cemu_tv() {
  local tv
  tv="$(find_tv_wid || true)"
  if [ -z "${tv:-}" ]; then
    return 1
  fi
  DISPLAY="$TV_DISPLAY" xdotool windowmap "$tv" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowmove "$tv" 0 0 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowsize "$tv" 1920 1080 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowstate --add FULLSCREEN "$tv" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowstate --add ABOVE "$tv" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowfocus "$tv" windowactivate "$tv" windowraise "$tv" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -id "$tv" -f STEAM_GAME 32c -set STEAM_GAME "$APPID" 2>/dev/null || true
  set_gamescope_focus "$tv" "$APPID"
}

watch_cemu_focus_loop() {
  local overlay=0
  while cemu_running; do
    if steam_overlay_active; then
      if [ "$overlay" -eq 0 ]; then
        DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
        DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$APPID" 2>/dev/null || true
        echo "STEAM_OVERLAY=1 — FOCUSED_APP=$STEAM_CLIENT_ID gfx=$APPID"
      fi
      overlay=1
    else
      overlay=0
      present_cemu_tv || true
    fi
    sleep 0.4
  done
}

start_focus_watch() {
  local pid
  stop_focus_watch
  present_cemu_tv || true
  watch_cemu_focus_loop >>"$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" >"$FOCUS_PIDFILE"
  echo "Cemu gamescope focus pid $pid"
}

start_mirror() {
  local wid="$1"
  stop_mirror
  place_pad_for_capture "$wid"
  echo "Mirroring GamePad xid $wid from $TV_DISPLAY onto $PAD_DISPLAY (ffplay x11grab)."
  # Leave the damaging paint running under ffplay. Headless gamescope
  # suspends its PipeWire source with no consumer; a static ffplay window
  # then stays connecting/black on video/1. Paint keeps the node emitting.
  # gst ximagesrc MIT-SHM BadMatch on off-screen GL windows and grabs a black
  # pixmap. ffmpeg/ffplay -window_id gets the GamePad drawable while it stays
  # mapped on-screen (under the raised TV).
  nohup env -u WAYLAND_DISPLAY DISPLAY="$PAD_DISPLAY" ffplay -hide_banner -loglevel warning \
    -fs -noborder -alwaysontop -sn -an \
    -fflags nobuffer -flags low_delay \
    -f x11grab -window_id "$wid" -framerate 30 -draw_mouse 0 -i "${TV_DISPLAY}.0" \
    >>"$LOG" 2>&1 &
  printf '%s\n' "$!" >"$MIRROR_PIDFILE"
  echo "GamePad mirror pid $!"
  # Headless gamescope sometimes maps ffplay at 640x480 before -fs applies.
  local i ff
  for i in 1 2 3 4 5; do
    ff="$(DISPLAY="$PAD_DISPLAY" xdotool search --class ffplay 2>/dev/null | tail -1 || true)"
    if [ -n "${ff:-}" ]; then
      DISPLAY="$PAD_DISPLAY" xdotool windowsize "$ff" 1920 1080 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xdotool windowmove "$ff" 0 0 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xdotool windowraise "$ff" 2>/dev/null || true
      break
    fi
    sleep 0.2
  done
}

if [ "$DO_STOP" -eq 1 ]; then
  stop_mirror
  stop_focus_watch
  echo "Left Cemu running (Steam Exit / Moonlight Quit still owns the game)."
  exit 0
fi

if [ ! -f "$ROM" ]; then
  echo "Missing ROM: $ROM"
  exit 1
fi

ensure_virtual_display || {
  echo "Headless gamescope $PAD_DISPLAY is not available."
  exit 1
}

bash "$ROOT/scripts/ensure-cemu-input.sh" >>"$LOG" 2>&1 || {
  echo "ensure-cemu-input.sh failed. See $LOG"
  exit 1
}

if [ -f "$RD_CONTROLLER" ]; then
  if ! python3 "$ROOT/scripts/bind-gamepad.py" cemu --xml "$RD_CONTROLLER" --match "$PAD_MATCH" --force; then
    python3 "$ROOT/scripts/bind-gamepad.py" cemu --xml "$RD_CONTROLLER" --match Sunshine --force || true
  fi
fi

write_rd_geometry || exit 1

if ! cemu_running; then
  if [ ! -x "$REAPER" ]; then
    echo "Missing Steam reaper at $REAPER"
    exit 1
  fi
  if [ -f /run/user/1000/gamescope-environment ]; then
    set -a
    # shellcheck disable=SC1091
    source /run/user/1000/gamescope-environment
    set +a
  fi
  export DISPLAY="$TV_DISPLAY"
  unset WAYLAND_DISPLAY
  export QT_QPA_PLATFORM=xcb
  export CEMU_GAMEMODE_DS=1
  export STEAM_OVERLAY=1
  export SteamAppId="$APPID"
  export SteamGameId="$APPID"
  export SteamOverlayGameId="$APPID"
  export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
  export SDL_JOYSTICK_HIDAPI=0
  export SDL_HIDAPI_JOYSTICK=0
  unset SDL_GAMECONTROLLER_IGNORE_DEVICES
  echo "SteamLaunch AppId=$APPID RetroDECK Cemu (CEMU_GAMEMODE_DS=1, no -f)."
  nohup "$REAPER" SteamLaunch AppId="$APPID" -- \
    flatpak run \
      --env=CEMU_GAMEMODE_DS=1 \
      --env=DISPLAY="$TV_DISPLAY" \
      --env=QT_QPA_PLATFORM=xcb \
      --env=STEAM_OVERLAY=1 \
      --env=SteamAppId="$APPID" \
      --env=SteamGameId="$APPID" \
      --env=SteamOverlayGameId="$APPID" \
      --unset-env=WAYLAND_DISPLAY \
      net.retrodeck.retrodeck \
      -e "%EMULATOR_CEMU% -g %ROM%" \
      "$ROM" \
    >>"$LOG" 2>&1 &
  echo "Launched pid $!"
  if ! wait_cemu; then
    echo "Cemu did not start. See $LOG"
    tail -40 "$LOG" || true
    exit 1
  fi
else
  echo "Cemu already running; mirroring GamePad View only."
fi

echo "Waiting for GamePad View on $TV_DISPLAY..."
if ! PAD_WID="$(wait_pad_wid)"; then
  echo "No GamePad View window. Cemu may still be on HDMI only. See $LOG"
  DISPLAY="$TV_DISPLAY" xdotool search --name 'Cemu' 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xwininfo -root -tree 2>/dev/null | grep -i -E 'cemu|pad|zelda' | head -20 || true
  exit 2
fi

start_mirror "$PAD_WID"
start_focus_watch
echo "Game Mode Cemu dual-stream: TV on $TV_DISPLAY (HDMI / video/0), GamePad mirrored to $PAD_DISPLAY (video/1)."
exit 0
