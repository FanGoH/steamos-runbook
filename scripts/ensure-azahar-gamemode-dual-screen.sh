#!/usr/bin/env bash
# Game Mode (:48200) Azahar dual-stream: 3DS top on session gamescope HDMI,
# bottom (touch) mirrored onto headless gamescope DISPLAY=:2.
#
# Standalone Flatpak org.azahar_emu.Azahar (not RetroDECK azahar-launcher).
# Steam overlay: reaper SteamLaunch with the game shortcut AppId, tag the
# Primary Window STEAM_GAME, and a focus watcher that yields HDMI when
# STEAM_OVERLAY=1 (FOCUSED_APP=769). QAM is Steam Quick Access (`...`),
# not 769: Steam blurs the game (`GAMESCOPE_BLUR_MODE`) and leaves
# FOCUSED_APP on Azahar. Do not raise Primary over that panel.
# sunshine-ds injects taps onto Secondary Window (not Cemu GamePad View).
# Hold-Select overlay lives in sunshine-ds, not steam-guide-from-select.py.
# Kill leftover Tk screensaver on :2 (sunshine-ds-kms-virtual) before
# ffplay or Moonlight video/1 stays the idle clock. --mirror-only remirrors
# without restarting Azahar (needed after kms --start recreates :2).
# --attach waits for an already-launching Azahar (no SteamLaunch).
# --quit stops Azahar + reaper + mirror (Steam Exit cannot SIGTERM a
# reaper whose parent is systemd --user, which is how the playbook launches).
# Tender 3DS Play while :48200 is BUSY execs this script from rom-launcher
# (standalone Flatpak, not RetroDECK azahar-launcher -f).
# Does not rewrite shortcuts.vdf. Does not touch :48100 / KWin.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
LOG="${ROOT}/logs/azahar-gamemode-ds.log"
MIRROR_PIDFILE="${ROOT}/logs/azahar-gamemode-pad-mirror.pid"
FOCUS_PIDFILE="${ROOT}/logs/azahar-gamemode-focus.pid"
PAINT_PIDFILE="${SUNSHINE_DS_KMS_VIRTUAL_PAINT_PIDFILE:-$ROOT/logs/sunshine-ds-gamemode-virtual-paint.pid}"
CEMU_MIRROR_PIDFILE="${ROOT}/logs/cemu-gamemode-pad-mirror.pid"
STEAM_CLIENT_ID=769
AZAHAR_INI="${AZAHAR_INI:-/home/${STEAMOS_USER:-deck}/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini}"
ROM="${AZAHAR_ROM:-/home/${STEAMOS_USER:-deck}/emulation/3ds/games/Super Mario 3D Land/Super Mario 3D Land (USA) (En,Fr,Es).3ds}"
APPID="${AZAHAR_STEAM_APPID:-2577949069}"
PAD_MATCH="${AZAHAR_PAD_MATCH:-Odin}"
TV_DISPLAY="${CEMU_TV_DISPLAY:-:0}"
PAD_DISPLAY="${CEMU_PAD_DISPLAY:-:2}"
REAPER="${STEAM_REAPER:-/home/${STEAMOS_USER:-deck}/.local/share/Steam/ubuntu12_32/reaper}"
VIRTUAL_HELPER="${ROOT}/scripts/sunshine-ds-gamemode-virtual.sh"

mkdir -p "$ROOT/logs"
: >>"$LOG"

usage() {
  sed -n '2,16p' "$0"
}

DO_STOP=0
DO_QUIT=0
DO_MIRROR_ONLY=0
DO_ATTACH=0
for arg in "$@"; do
  case "$arg" in
    --stop) DO_STOP=1 ;;
    --quit) DO_QUIT=1 ;;
    --mirror-only) DO_MIRROR_ONLY=1 ;;
    --attach) DO_ATTACH=1 ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "usage: $0 [--stop|--mirror-only|--attach|--quit]" >&2
      exit 2
      ;;
  esac
done

azahar_running() {
  ps -eo comm= | grep -qx azahar
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

# pgrep -x ffplay, then argv / DISPLAY. Never pgrep -f sunshine.
kill_pad_x11grab() {
  local pid cmd disp
  command -v pgrep >/dev/null 2>&1 || return 0
  for pid in $(pgrep -x ffplay || true); do
    [ -r "/proc/$pid/cmdline" ] || continue
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *x11grab*) ;;
      *) continue ;;
    esac
    disp="$(tr '\0' '\n' <"/proc/$pid/environ" 2>/dev/null | sed -n 's/^DISPLAY=//p' | head -1 || true)"
    case "$disp" in
      "$PAD_DISPLAY"|"${PAD_DISPLAY}.0"|":2"|":2.0")
        echo "Stopping leftover Azahar x11grab ffplay pid $pid."
        kill "$pid" 2>/dev/null || true
        ;;
    esac
  done
}

stop_mirror() {
  local pid
  pid="$(cat "$MIRROR_PIDFILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ]; then
    echo "Stopping Azahar bottom-screen mirror pid $pid."
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$MIRROR_PIDFILE"
  pid="$(cat "$CEMU_MIRROR_PIDFILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ]; then
    comm="$(ps -o comm= -p "$pid" 2>/dev/null || true)"
    if [ "$comm" = ffplay ]; then
      echo "Stopping leftover Cemu ffplay pid $pid."
      kill "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$CEMU_MIRROR_PIDFILE"
  kill_pad_x11grab
}

stop_focus_watch() {
  local pid
  pid="$(cat "$FOCUS_PIDFILE" 2>/dev/null || true)"
  if [ -n "${pid:-}" ] && [ -d "/proc/$pid" ]; then
    echo "Stopping Azahar gamescope focus pid $pid."
    kill "$pid" 2>/dev/null || true
  fi
  rm -f "$FOCUS_PIDFILE"
}

stop_azahar() {
  bash "$ROOT/scripts/sunshine-app-stop.sh" azahar || true
  local pid cmd
  for pid in $(ps -eo pid=,comm= | awk '$2=="reaper"{print $1}'); do
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *"AppId=${APPID}"*|*"org.azahar_emu.Azahar"*)
        echo "Stopping Azahar SteamLaunch reaper pid $pid."
        kill "$pid" 2>/dev/null || true
        ;;
    esac
  done
}

write_azahar_layout() {
  python3 - "$AZAHAR_INI" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text() if path.is_file() else ""

def set_key(src, key, value):
    pat = re.compile(r"^" + re.escape(key) + r"=.*$", re.M)
    repl = f"{key}={value}"
    if pat.search(src):
        src = pat.sub(lambda _m: repl, src, count=1)
    else:
        src += f"\n{repl}\n"
    dkey = key + "\\default"
    dpat = re.compile(r"^" + re.escape(dkey) + r"=.*$", re.M)
    drepl = dkey + "=false"
    if dpat.search(src):
        src = dpat.sub(lambda _m: drepl, src, count=1)
    else:
        src += f"\n{drepl}\n"
    return src

for key, val in [
    ("layout_option", "4"),
    ("secondary_display_layout", "2"),
    ("fullscreen", "false"),
    ("singleWindowMode", "false"),
    ("confirmClose", "false"),
    ("pauseWhenInBackground", "false"),
    ("screen_bottom_stretch", "true"),
    ("screen_top_stretch", "true"),
]:
    text = set_key(text, key, val)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(text)
print("Wrote Azahar separate-windows layout in", path)
PY
}

bind_odin() {
  if python3 "$ROOT/scripts/bind-gamepad.py" azahar --ini "$AZAHAR_INI" --match "$PAD_MATCH" --force; then
    return 0
  fi
  echo "No pad matched ${PAD_MATCH}; trying Odin2 then Sunshine."
  python3 "$ROOT/scripts/bind-gamepad.py" azahar --ini "$AZAHAR_INI" --match Odin2 --force \
    || python3 "$ROOT/scripts/bind-gamepad.py" azahar --ini "$AZAHAR_INI" --match Sunshine --force \
    || return 1
}

find_wid() {
  # $1 caption needle, $2 varname for xid. Sets TV_DISPLAY in this shell.
  # Do not capture stdout — $(find_wid) drops TV_DISPLAY so x11grab uses :0
  # for a :1 xid (Thor bottom stays the idle clock).
  local needle="$1" dest="$2" d id name
  printf -v "$dest" '%s' ""
  for d in "$TV_DISPLAY" :1 :0; do
    [ -n "$d" ] || continue
    for id in $(DISPLAY="$d" xdotool search --name "$needle" 2>/dev/null || true); do
      name="$(DISPLAY="$d" xdotool getwindowname "$id" 2>/dev/null || true)"
      case "$name" in
        *"$needle"*)
          TV_DISPLAY="$d"
          printf -v "$dest" '%s' "$id"
          return 0
          ;;
      esac
    done
  done
  return 1
}

find_primary_wid() { find_wid 'Primary Window' PRIMARY_WID; }
find_secondary_wid() { find_wid 'Secondary Window' SECONDARY_WID; }

wait_azahar() {
  local i=0
  while [ "$i" -lt 45 ]; do
    if azahar_running; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

wait_game_windows() {
  local i=0
  while [ "$i" -lt 60 ]; do
    if find_primary_wid && find_secondary_wid; then
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

steam_overlay_active() {
  local wid val map
  command -v xprop >/dev/null 2>&1 || return 1
  wid="$(DISPLAY="$TV_DISPLAY" xwininfo -root -tree 2>/dev/null | awk '/Steam Big Picture Mode/{print $1; exit}')"
  if [ -n "${wid:-}" ]; then
    map="$(DISPLAY="$TV_DISPLAY" xwininfo -id "$wid" 2>/dev/null | awk '/Map State/{print $3}')"
    if [ "${map:-}" = "IsViewable" ]; then
      val="$(DISPLAY="$TV_DISPLAY" xprop -id "$wid" STEAM_OVERLAY 2>/dev/null | awk -F'= ' '{print $2}')"
      if [ "${val:-0}" = "1" ]; then
        return 0
      fi
    fi
  fi
  command -v xdotool >/dev/null 2>&1 || return 1
  for wid in $(DISPLAY="$TV_DISPLAY" xdotool search --class steam 2>/dev/null || true) \
             $(DISPLAY="$TV_DISPLAY" xdotool search --class steamwebhelper 2>/dev/null || true); do
    map="$(DISPLAY="$TV_DISPLAY" xwininfo -id "$wid" 2>/dev/null | awk '/Map State/{print $3}')"
    [ "${map:-}" = "IsViewable" ] || continue
    val="$(DISPLAY="$TV_DISPLAY" xprop -id "$wid" STEAM_OVERLAY 2>/dev/null | awk -F'= ' '{print $2}')"
    if [ "${val:-0}" = "1" ]; then
      return 0
    fi
  done
  return 1
}

# Steam Quick Access Menu (`...`). Game stays FOCUSED_APP; gamescope blurs it.
steam_qam_active() {
  local mode
  command -v xprop >/dev/null 2>&1 || return 1
  mode="$(DISPLAY="${TV_DISPLAY:-:0}" xprop -root GAMESCOPE_BLUR_MODE 2>/dev/null | awk -F'= ' '{print $2}' | awk -F, '{print $1}' | tr -d ' ')"
  [ -n "${mode:-}" ] && [ "$mode" != "0" ]
}

# keepAbove on Primary covers the QAM side panel.
lower_azahar_for_steam_ui() {
  local wid
  find_primary_wid || true
  find_secondary_wid || true
  for wid in "${PRIMARY_WID:-}" "${SECONDARY_WID:-}"; do
    [ -n "${wid:-}" ] || continue
    DISPLAY="$TV_DISPLAY" xdotool windowstate --remove ABOVE "$wid" 2>/dev/null || true
  done
}

focused_app() {
  DISPLAY="$TV_DISPLAY" xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}'
}

set_gamescope_focus() {
  local id="$1" app="$2"
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$id" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$app" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$app" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$id" 2>/dev/null || true
}

present_primary() {
  find_primary_wid || return 1
  DISPLAY="$TV_DISPLAY" xdotool windowmap "$PRIMARY_WID" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowmove "$PRIMARY_WID" 0 0 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowsize "$PRIMARY_WID" 1920 1080 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowstate --add ABOVE "$PRIMARY_WID" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowfocus "$PRIMARY_WID" windowactivate "$PRIMARY_WID" windowraise "$PRIMARY_WID" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xprop -id "$PRIMARY_WID" -f STEAM_GAME 32c -set STEAM_GAME "$APPID" 2>/dev/null || true
  set_gamescope_focus "$PRIMARY_WID" "$APPID"
}

watch_azahar_focus_loop() {
  # Overlay: Hold-Select → STEAM_OVERLAY=1 + FOCUSED_APP=769.
  # QAM: `...` → GAMESCOPE_BLUR_MODE!=0, FOCUSED_APP stays the game.
  # Raising Primary (keepAbove) covers that side panel.
  local ui=0 app
  while azahar_running; do
    app="$(focused_app)"
    if steam_overlay_active; then
      lower_azahar_for_steam_ui
      if [ "$ui" -eq 0 ]; then
        DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
        DISPLAY="$TV_DISPLAY" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$APPID" 2>/dev/null || true
        echo "STEAM_OVERLAY=1 — FOCUSED_APP=$STEAM_CLIENT_ID gfx=$APPID"
      fi
      ui=1
    elif steam_qam_active; then
      lower_azahar_for_steam_ui
      if [ "$ui" -eq 0 ]; then
        echo "Steam QAM (GAMESCOPE_BLUR_MODE) — yielding (no raise, leave FOCUSED_APP)"
      fi
      ui=1
    elif [ "$app" = "$STEAM_CLIENT_ID" ]; then
      lower_azahar_for_steam_ui
      if [ "$ui" -eq 0 ]; then
        echo "FOCUSED_APP=$STEAM_CLIENT_ID — yielding to Steam (no reclaim)"
      fi
      ui=1
    elif [ "$app" != "$APPID" ]; then
      ui=0
      present_primary || true
    else
      ui=0
    fi
    sleep 0.4
  done
  echo "Azahar exited — stopping bottom mirror so :2 can screensaver again."
  stop_mirror
  bash "$VIRTUAL_HELPER" --paint >/dev/null 2>&1 || true
}

start_focus_watch() {
  stop_focus_watch
  bash "$ROOT/scripts/start-emu-steam-ui-inhibit.sh" >/dev/null 2>&1 || true
  present_primary || true
  watch_azahar_focus_loop >>"$LOG" 2>&1 &
  printf '%s\n' "$!" >"$FOCUS_PIDFILE"
  echo "Azahar gamescope focus pid $!"
}

place_secondary_for_capture() {
  local wid="$1"
  DISPLAY="$TV_DISPLAY" xdotool windowmap "$wid" 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowsize "$wid" 1920 1080 2>/dev/null || true
  DISPLAY="$TV_DISPLAY" xdotool windowmove "$wid" 0 0 2>/dev/null || true
  present_primary || true
}

start_mirror() {
  local wid="$1"
  stop_mirror
  stop_paint
  place_secondary_for_capture "$wid"
  echo "Mirroring Azahar Secondary xid $wid from $TV_DISPLAY onto $PAD_DISPLAY (ffplay x11grab)."
  nohup env -u WAYLAND_DISPLAY \
    DISPLAY="$PAD_DISPLAY" SDL_VIDEODRIVER=x11 SDL_AUDIODRIVER=dummy \
    ffplay -hide_banner -loglevel warning \
    -fs -noborder -alwaysontop -sn -an \
    -fflags nobuffer -flags low_delay \
    -f x11grab -window_id "$wid" -framerate 30 -draw_mouse 0 -i "${TV_DISPLAY}.0" \
    >>"$LOG" 2>&1 &
  printf '%s\n' "$!" >"$MIRROR_PIDFILE"
  echo "bottom-screen mirror pid $!"
  local i ff
  for i in 1 2 3 4 5 6 7 8 9 10; do
    ff="$(DISPLAY="$PAD_DISPLAY" xdotool search --class ffplay 2>/dev/null | tail -1 || true)"
    if [ -n "${ff:-}" ]; then
      DISPLAY="$PAD_DISPLAY" xdotool windowmap "$ff" 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xdotool windowsize "$ff" 1920 1080 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xdotool windowmove "$ff" 0 0 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xdotool windowstate --add FULLSCREEN "$ff" 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xdotool windowstate --add ABOVE "$ff" 2>/dev/null || true
      DISPLAY="$PAD_DISPLAY" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$ff" 2>/dev/null || true
      break
    fi
    sleep 0.2
  done
}

minimize_library() {
  local id name
  for id in $(DISPLAY="$TV_DISPLAY" xdotool search --class Azahar 2>/dev/null || true); do
    name="$(DISPLAY="$TV_DISPLAY" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      *Primary*|*Secondary*) continue ;;
      Azahar\ 2126*|Azahar\ 2*)
        DISPLAY="$TV_DISPLAY" xdotool windowminimize "$id" 2>/dev/null || true
        echo "Minimized library $id ($name)"
        ;;
    esac
  done
}

if [ "$DO_QUIT" -eq 1 ]; then
  stop_focus_watch
  stop_azahar
  stop_mirror
  bash "$VIRTUAL_HELPER" --paint >/dev/null 2>&1 || true
  bash "$ROOT/scripts/restore-steam-gamescope-focus.sh" 2>/dev/null || true
  echo "Quit Azahar (SteamLaunch reaper + windows). Steam Exit can finish."
  exit 0
fi

if [ "$DO_STOP" -eq 1 ]; then
  stop_mirror
  stop_focus_watch
  bash "$VIRTUAL_HELPER" --paint >/dev/null 2>&1 || true
  echo "Left Azahar running (use --quit or sunshine-app-stop.sh to end the game)."
  exit 0
fi

if [ "$DO_MIRROR_ONLY" -eq 1 ]; then
  ensure_virtual_display || {
    echo "Headless gamescope $PAD_DISPLAY is not available."
    exit 1
  }
  if ! azahar_running; then
    echo "Azahar is not running."
    exit 2
  fi
  if ! wait_game_windows; then
    echo "No Azahar Primary/Secondary windows."
    exit 2
  fi
  find_secondary_wid || {
    echo "No Azahar Secondary Window."
    exit 2
  }
  echo "Remirroring Secondary=$SECONDARY_WID from $TV_DISPLAY onto $PAD_DISPLAY (no Azahar restart)."
  start_mirror "$SECONDARY_WID"
  present_primary || true
  start_focus_watch
  exit 0
fi

# Already launching (or host-opened). Do not SteamLaunch again.
if [ "$DO_ATTACH" -eq 1 ]; then
  focus_pid="$(cat "$FOCUS_PIDFILE" 2>/dev/null || true)"
  if [ -n "${focus_pid:-}" ] && [ -d "/proc/$focus_pid" ]; then
    echo "Azahar dual-stream already watching pid $focus_pid; remirroring only."
    if find_secondary_wid; then
      start_mirror "$SECONDARY_WID"
    fi
    present_primary || true
    exit 0
  fi
  ensure_virtual_display || {
    echo "Headless gamescope $PAD_DISPLAY is not available."
    exit 1
  }
  if ! wait_azahar; then
    echo "Azahar did not start (attach). See $LOG"
    exit 1
  fi
  bind_odin || echo "Azahar bind failed; continuing with whatever GUID is in qt-config.ini."
  echo "Waiting for Primary/Secondary windows (attach)..."
  if ! wait_game_windows; then
    echo "No Azahar game windows (attach). Watching for exit so :2 can screensaver."
    start_focus_watch
    exit 2
  fi
  find_primary_wid
  find_secondary_wid
  echo "Primary=$PRIMARY_WID Secondary=$SECONDARY_WID on $TV_DISPLAY"
  minimize_library
  start_mirror "$SECONDARY_WID"
  start_focus_watch
  echo "Attached Game Mode Azahar dual-stream: top on $TV_DISPLAY, bottom on $PAD_DISPLAY."
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

write_azahar_layout || exit 1
bind_odin || echo "Azahar bind failed; continuing with whatever GUID is in qt-config.ini."

# Azahar reads GUID at start. Restart so Odin (not Thor) is player 1.
if azahar_running; then
  echo "Restarting Azahar so the Odin GUID is picked up."
  stop_focus_watch
  stop_mirror
  stop_azahar
  i=0
  while [ "$i" -lt 25 ] && azahar_running; do
    sleep 0.2
    i=$((i + 1))
  done
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
export STEAM_OVERLAY=1
export SteamAppId="$APPID"
export SteamGameId="$APPID"
export SteamOverlayGameId="$APPID"
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
SDL_EXCEPT="$(python3 "$ROOT/scripts/pad_profile.py" sdl-except)"
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$SDL_EXCEPT"

if [ ! -x "$REAPER" ]; then
  echo "Missing Steam reaper at $REAPER"
  exit 1
fi

echo "SteamLaunch AppId=$APPID standalone Azahar (pad match $PAD_MATCH)."
nohup "$REAPER" SteamLaunch AppId="$APPID" -- \
  flatpak run \
    --env=DISPLAY="$TV_DISPLAY" \
    --env=QT_QPA_PLATFORM=xcb \
    --env=STEAM_OVERLAY=1 \
    --env=SteamAppId="$APPID" \
    --env=SteamGameId="$APPID" \
    --env=SteamOverlayGameId="$APPID" \
    --env=SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1 \
    --env=SDL_JOYSTICK_HIDAPI=0 \
    --env=SDL_HIDAPI_JOYSTICK=0 \
    --unset-env=WAYLAND_DISPLAY \
    org.azahar_emu.Azahar \
    "$ROM" >>"$LOG" 2>&1 &
echo "Launched pid $!"

if ! wait_azahar; then
  echo "Azahar did not start. See $LOG"
  tail -40 "$LOG" || true
  exit 1
fi

echo "Waiting for Primary/Secondary windows on $TV_DISPLAY..."
if ! wait_game_windows; then
  echo "No Azahar game windows. See $LOG"
  DISPLAY="$TV_DISPLAY" xwininfo -root -tree 2>/dev/null | grep -i azahar | head -20 || true
  exit 2
fi

find_primary_wid
find_secondary_wid
echo "Primary=$PRIMARY_WID Secondary=$SECONDARY_WID on $TV_DISPLAY"
minimize_library
start_mirror "$SECONDARY_WID"
start_focus_watch
echo "Game Mode Azahar dual-stream: top on $TV_DISPLAY (HDMI / video/0), bottom mirrored to $PAD_DISPLAY (video/1)."
echo "Hold-Select overlay is in sunshine-ds. Focus watcher yields FOCUSED_APP=769 while overlay is up."
echo "Pad match: $PAD_MATCH (restart applied the GUID)."
exit 0
