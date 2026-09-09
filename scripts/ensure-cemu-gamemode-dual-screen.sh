#!/usr/bin/env bash
# Game Mode (:48200) Cemu dual-stream: TV on session gamescope HDMI, GamePad
# View mirrored onto the headless gamescope DISPLAY=:2 PipeWire node.
#
# Steam overlay: reaper SteamLaunch with the Wind Waker HD shortcut AppId,
# then the same RetroDECK Cemu command as that tile — with CEMU_GAMEMODE_DS=1
# so the wrapper does not force -f. Does not rewrite shortcuts.vdf.
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
PAINT_PIDFILE="${SUNSHINE_DS_KMS_VIRTUAL_PAINT_PIDFILE:-$ROOT/logs/sunshine-ds-gamemode-virtual-paint.pid}"
RD_SETTINGS="${CEMU_RD_SETTINGS:-/home/${STEAMOS_USER:-deck}/.var/app/net.retrodeck.retrodeck/config/Cemu/settings.xml}"
RD_CONTROLLER="${CEMU_RD_CONTROLLER:-/home/${STEAMOS_USER:-deck}/.var/app/net.retrodeck.retrodeck/config/Cemu/controllerProfiles/controller0.xml}"
ROM="${CEMU_ROM:-/home/${STEAMOS_USER:-deck}/retrodeck/roms/wiiu/Legend of Zelda, The - The Wind Waker HD (USA, Asia) (En,Fr,Es).wux}"
APPID="${CEMU_STEAM_APPID:-2374129079}"
PAD_MATCH="${CEMU_PAD_MATCH:-Sunshine}"
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
set_xy(root, "pad_position", 1920, 0)
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

place_pad_offscreen() {
  local wid="$1"
  DISPLAY="$TV_DISPLAY" xdotool windowmap "$wid" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowsize "$wid" 1920 1080 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowmove "$wid" 1920 0 2>/dev/null || true
}

start_mirror() {
  local wid="$1" sink
  stop_paint
  stop_mirror
  place_pad_offscreen "$wid"
  sink=xvimagesink
  if ! DISPLAY="$PAD_DISPLAY" gst-inspect-1.0 xvimagesink >/dev/null 2>&1; then
    sink=ximagesink
  fi
  echo "Mirroring GamePad xid $wid from $TV_DISPLAY onto $PAD_DISPLAY ($sink)."
  # Capture the Cemu GamePad X window (session gamescope) and scan it out on
  # the headless gamescope so sunshine-ds-kms video/1 shows the real pad.
  nohup env DISPLAY="$PAD_DISPLAY" gst-launch-1.0 -e \
    ximagesrc "display-name=$TV_DISPLAY" "xid=$wid" use-damage=false show-pointer=false \
    ! videoconvert \
    ! "$sink" force-aspect-ratio=true sync=false \
    >>"$LOG" 2>&1 &
  printf '%s\n' "$!" >"$MIRROR_PIDFILE"
  echo "GamePad mirror pid $!"
}

if [ "$DO_STOP" -eq 1 ]; then
  stop_mirror
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
echo "Game Mode Cemu dual-stream: TV on $TV_DISPLAY (HDMI / video/0), GamePad mirrored to $PAD_DISPLAY (video/1)."
exit 0
