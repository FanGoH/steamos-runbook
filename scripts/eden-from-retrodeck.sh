#!/usr/bin/env bash
# Launch Eden so Game Mode / gamescope actually presents the window.
#
# RetroDECK starts this via `flatpak-spawn --host`, which drops Game Mode
# display env. Even with a visible X window, gamescope keeps compositing
# Steam Big Picture (app 769) until GAMESCOPE_FOCUSED_* points at Eden.
set -euo pipefail

EDEN_BIN="${EDEN_BIN:-/home/deck/Applications/Eden.appimage}"
GAMESCOPE_ENV="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/gamescope-environment"
STEAM_CLIENT_ID=769
FOCUS_LOG="${EDEN_FOCUS_LOG:-/tmp/eden-gamescope-focus.log}"
SELF="$(readlink -f "$0")"
STEAM_HOME="${STEAM_HOME:-/home/deck/.local/share/Steam}"

if [ -f "$GAMESCOPE_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$GAMESCOPE_ENV"
  set +a
fi

if [ -z "${DISPLAY:-}" ] || [ ! -S /tmp/.X11-unix/X"${DISPLAY#:}" ]; then
  if [ -S /tmp/.X11-unix/X0 ]; then
    export DISPLAY=:0
  fi
fi
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"
export ENABLE_GAMESCOPE_WSI="${ENABLE_GAMESCOPE_WSI:-1}"
# When gamescope focus is on Steam overlay, Eden must not keep eating the pad.
export SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS="${SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS:-0}"
if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/gamescope-0" ]; then
  export WAYLAND_DISPLAY=gamescope-0
  export GAMESCOPE_WAYLAND_DISPLAY="${GAMESCOPE_WAYLAND_DISPLAY:-gamescope-0}"
fi

log() {
  printf '%s %s\n' "$(date -Iseconds)" "$*" >>"$FOCUS_LOG"
}

# Steam client (769) is a Valve constant. RetroDECK's non-Steam shortcut id is
# not: it lives in shortcuts.vdf and can change if the shortcut is re-added.
# Prefer the env Steam already set, then the currently focused gamescope app,
# then parse shortcuts.vdf for AppName=RetroDECK.
is_game_app_id() {
  local id="${1:-}"
  [ -n "$id" ] && [ "$id" != "0" ] && [ "$id" != "$STEAM_CLIENT_ID" ]
}

shortcut_app_id_from_vdf() {
  local name="${1:-RetroDECK}"
  python3 - "$STEAM_HOME" "$name" <<'PY'
import sys
from pathlib import Path
steam, name = sys.argv[1], sys.argv[2].encode()
needle = b"\x01AppName\x00" + name + b"\x00"
for p in Path(steam, "userdata").glob("*/config/shortcuts.vdf"):
    data = p.read_bytes()
    i = 0
    while True:
        j = data.find(needle, i)
        if j < 0:
            break
        k = data.rfind(b"\x02appid\x00", max(0, j - 160), j)
        if k >= 0:
            appid = int.from_bytes(data[k + 7 : k + 11], "little")
            if appid:
                print(appid)
                sys.exit(0)
        i = j + 1
sys.exit(1)
PY
}

resolve_steam_app_id() {
  local id=""
  if is_game_app_id "${STEAM_APP_ID:-}"; then
    log "SteamAppId already set: $STEAM_APP_ID"
    export SteamAppId="$STEAM_APP_ID"
    export SteamGameId="${SteamGameId:-$STEAM_APP_ID}"
    return 0
  fi
  if is_game_app_id "${SteamAppId:-}"; then
    id="$SteamAppId"
    log "SteamAppId from env: $id"
  else
    id="$(DISPLAY="${DISPLAY:-:0}" xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}')"
    if is_game_app_id "$id"; then
      log "SteamAppId from gamescope focus: $id"
    else
      id="$(shortcut_app_id_from_vdf RetroDECK 2>/dev/null || true)"
      if is_game_app_id "$id"; then
        log "SteamAppId from shortcuts.vdf: $id"
      else
        id="$(DISPLAY="${DISPLAY:-:0}" xprop -root GAMESCOPECTRL_BASELAYER_APPID 2>/dev/null \
          | tr -d ' ' | awk -F'= ' '{print $2}' | tr ',' '\n' | grep -Ex '[0-9]+' \
          | grep -vx "$STEAM_CLIENT_ID" | grep -vx '413091' | head -n 1 || true)"
        if is_game_app_id "$id"; then
          log "SteamAppId from gamescope baselayer: $id"
        else
          log "ERROR: could not resolve RetroDECK Steam shortcut id"
          return 1
        fi
      fi
    fi
  fi
  STEAM_APP_ID="$id"
  export STEAM_APP_ID
  export SteamAppId="$STEAM_APP_ID"
  export SteamGameId="${SteamGameId:-$STEAM_APP_ID}"
}

eden_window_id() {
  local display="${DISPLAY:-:0}" id name
  command -v xdotool >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$display" xdotool search --class eden 2>/dev/null || true); do
    name="$(DISPLAY="$display" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      "Eden |"*)
        printf '%s\n' "$id"
        return 0
        ;;
    esac
  done
  return 1
}

steam_bpm_window_id() {
  local display="${DISPLAY:-:0}" id name
  command -v xdotool >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$display" xdotool search --class steam 2>/dev/null || true) \
            $(DISPLAY="$display" xdotool search --class steamwebhelper 2>/dev/null || true); do
    name="$(DISPLAY="$display" xdotool getwindowname "$id" 2>/dev/null || true)"
    case "$name" in
      "Steam Big Picture Mode")
        printf '%s\n' "$id"
        return 0
        ;;
    esac
  done
  DISPLAY="$display" xdotool search --name 'Steam Big Picture Mode' 2>/dev/null | head -n 1
}

focused_app() {
  DISPLAY="${DISPLAY:-:0}" xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null | awk -F'= ' '{print $2}'
}

window_cardinal() {
  local display="${DISPLAY:-:0}" wid="$1" atom="$2"
  DISPLAY="$display" xprop -id "$wid" "$atom" 2>/dev/null | awk -F'= ' '{print $2}'
}

# True when Steam itself flags overlay/input grab. Do not treat
# GAMESCOPE_FOCUSED_APP=769 as overlay here: we may set that ourselves.
steam_overlay_active() {
  local display="${DISPLAY:-:0}" wid val
  command -v xdotool >/dev/null 2>&1 || return 1
  command -v xprop >/dev/null 2>&1 || return 1
  for wid in $(DISPLAY="$display" xdotool search --class steam 2>/dev/null || true) \
             $(DISPLAY="$display" xdotool search --class steamwebhelper 2>/dev/null || true); do
    for atom in STEAM_OVERLAY STEAM_INPUT_FOCUS; do
      val="$(window_cardinal "$wid" "$atom")"
      if [ "${val:-0}" = "1" ]; then
        return 0
      fi
    done
  done
  return 1
}

eden_main_pids() {
  local pid cmd
  for pid in /proc/[0-9]*; do
    cmd="$(tr '\0' ' ' <"$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *'/tmp/.mount_Eden'*/bin/eden*)
        printf '%s\n' "${pid##*/}"
        ;;
    esac
  done
}

pause_eden_for_overlay() {
  local pid
  for pid in $(eden_main_pids); do
    kill -STOP "$pid" 2>/dev/null || true
  done
}

resume_eden_from_overlay() {
  local pid
  for pid in $(eden_main_pids); do
    kill -CONT "$pid" 2>/dev/null || true
  done
}

# Qt title/status bars stay mapped when Eden is windowed (typically 22px / 24px).
eden_chrome_visible() {
  local display="${DISPLAY:-:0}" id w h mapped
  command -v xdotool >/dev/null 2>&1 || return 1
  command -v xwininfo >/dev/null 2>&1 || return 1
  for id in $(DISPLAY="$display" xdotool search --class eden 2>/dev/null || true); do
    mapped="$(DISPLAY="$display" xwininfo -id "$id" 2>/dev/null | awk -F': ' '/Map State/ {print $2; exit}')"
    [ "$mapped" = "IsViewable" ] || continue
    w="$(DISPLAY="$display" xwininfo -id "$id" 2>/dev/null | awk '/Width:/ {print $2; exit}')"
    h="$(DISPLAY="$display" xwininfo -id "$id" 2>/dev/null | awk '/Height:/ {print $2; exit}')"
    if [ "${w:-0}" -ge 1000 ] && [ "${h:-0}" -ge 16 ] && [ "${h:-0}" -le 40 ]; then
      return 0
    fi
  done
  return 1
}

make_eden_fullscreen() {
  local display="${DISPLAY:-:0}"
  local id sw sh
  id="$(eden_window_id)" || return 1
  sw=1920
  sh=1080
  if read -r sw sh < <(DISPLAY="$display" xdotool getdisplaygeometry 2>/dev/null); then
    :
  fi
  DISPLAY="$display" xdotool windowmap "$id" windowmove "$id" 0 0 2>/dev/null || true
  DISPLAY="$display" xdotool windowsize "$id" "$sw" "$sh" 2>/dev/null || true
  DISPLAY="$display" xdotool windowstate --add FULLSCREEN "$id" 2>/dev/null || true
  DISPLAY="$display" xdotool windowstate --add ABOVE "$id" 2>/dev/null || true
  # F11 is Eden's real toggle; gamescope ignores EWMH fullscreen.
  # `xdotool key --window` is dropped under gamescope — focus the X window first.
  if [ "${F11_SENT:-0}" -eq 0 ] && eden_chrome_visible; then
    DISPLAY="$display" xdotool windowfocus "$id" windowactivate "$id" 2>/dev/null || true
    sleep 0.1
    DISPLAY="$display" xdotool key F11 2>/dev/null || true
    F11_SENT=1
    log "sent F11 to hide Qt chrome window=$id ${sw}x${sh}"
  fi
}

set_gamescope_focus() {
  local id="$1"
  local app="$2"
  local display="${DISPLAY:-:0}"
  DISPLAY="$display" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$id" 2>/dev/null || true
  DISPLAY="$display" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$app" 2>/dev/null || true
  DISPLAY="$display" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$app" 2>/dev/null || true
  DISPLAY="$display" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$id" 2>/dev/null || true
}

# Overlay: Steam gets input (FOCUSED_APP/WINDOW), Eden stays the visible layer.
hand_input_to_steam_overlay() {
  local display="${DISPLAY:-:0}"
  local bpm eden
  bpm="$(steam_bpm_window_id || true)"
  eden="$(eden_window_id || true)"
  if [ -n "${bpm:-}" ]; then
    DISPLAY="$display" xprop -root -f GAMESCOPE_FOCUSED_WINDOW 32c -set GAMESCOPE_FOCUSED_WINDOW "$bpm" 2>/dev/null || true
  fi
  DISPLAY="$display" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
  if [ -n "${eden:-}" ]; then
    DISPLAY="$display" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$STEAM_APP_ID" 2>/dev/null || true
    DISPLAY="$display" xprop -root -f GAMESCOPECTRL_BASELAYER_WINDOW 32c -set GAMESCOPECTRL_BASELAYER_WINDOW "$eden" 2>/dev/null || true
  fi
  log "overlay input -> Steam bpm=${bpm:-none} gfx=$STEAM_APP_ID eden=${eden:-none}"
}

focus_eden_in_gamescope() {
  local display="${DISPLAY:-:0}"
  local id
  id="$(eden_window_id)" || return 1
  DISPLAY="$display" xdotool windowmap "$id" windowmove "$id" 0 0 \
    windowraise "$id" windowactivate "$id" 2>/dev/null || true
  make_eden_fullscreen || true
  DISPLAY="$display" xprop -id "$id" -f STEAM_GAME 32c -set STEAM_GAME "$STEAM_APP_ID" 2>/dev/null || true
  set_gamescope_focus "$id" "$STEAM_APP_ID"
  log "focused Eden window=$id app=$STEAM_APP_ID"
  return 0
}

restore_steam_focus() {
  local id
  id="$(steam_bpm_window_id || true)"
  if [ -n "${id:-}" ]; then
    set_gamescope_focus "$id" "$STEAM_CLIENT_ID"
    log "restored Steam BPM window=$id"
  else
    DISPLAY="${DISPLAY:-:0}" xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$STEAM_CLIENT_ID" 2>/dev/null || true
    DISPLAY="${DISPLAY:-:0}" xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$STEAM_CLIENT_ID" 2>/dev/null || true
    log "restored Steam app id only (no BPM window)"
  fi
}

eden_bin_running() {
  local pid cmd
  for pid in /proc/[0-9]*; do
    cmd="$(tr '\0' ' ' <"$pid/cmdline" 2>/dev/null || true)"
    case "$cmd" in
      *'/tmp/.mount_Eden'*/bin/eden*|*/Applications/Eden.appimage*)
        return 0
        ;;
    esac
  done
  return 1
}

watch_eden_focus() {
  : >"$FOCUS_LOG"
  log "watch start"
  F11_SENT=0
  local waited=0
  while [ "$waited" -lt 120 ]; do
    if focus_eden_in_gamescope; then
      break
    fi
    sleep 0.5
    waited=$((waited + 1))
  done
  if ! eden_window_id >/dev/null; then
    log "watch gave up waiting for Eden window"
    exit 1
  fi
  local overlay=0 overlay_via="" app
  make_eden_fullscreen || true
  while eden_bin_running; do
    app="$(focused_app)"
    if steam_overlay_active; then
      if [ "$overlay" -eq 0 ]; then
        log "Steam overlay atoms on — pause Eden, hand input to Steam"
        pause_eden_for_overlay
        hand_input_to_steam_overlay
        overlay=1
        overlay_via=atoms
      fi
    elif [ "$overlay" -eq 1 ] && [ "$overlay_via" = "atoms" ]; then
      log "Steam overlay atoms off — resume Eden"
      resume_eden_from_overlay
      overlay=0
      overlay_via=""
      focus_eden_in_gamescope || true
    elif [ "$app" = "$STEAM_CLIENT_ID" ]; then
      if [ "$overlay" -eq 0 ]; then
        log "gamescope focus is Steam 769 — pausing Eden (leave Steam focused)"
        pause_eden_for_overlay
        overlay=1
        overlay_via=focus
      fi
    else
      if [ "$overlay" -eq 1 ]; then
        log "Steam overlay off — resume Eden"
        resume_eden_from_overlay
        overlay=0
        overlay_via=""
        focus_eden_in_gamescope || true
      elif [ "$app" != "$STEAM_APP_ID" ]; then
        log "focus stolen (app=$app); reclaiming"
        focus_eden_in_gamescope || true
      elif [ "$F11_SENT" -eq 0 ] && eden_chrome_visible; then
        log "Qt chrome still visible; sending F11"
        make_eden_fullscreen || true
      fi
    fi
    sleep 0.2
  done
  resume_eden_from_overlay
  restore_steam_focus
  log "watch exit (Eden gone)"
}

resolve_rom() {
  local path="$1"
  if [ -f "$path" ]; then
    printf '%s\n' "$path"
    return 0
  fi
  if [ -d "$path" ]; then
    local match
    match="$(find "$path" -maxdepth 1 -type f \( \
      -iname '*.xci' -o -iname '*.nsp' -o -iname '*.nca' -o -iname '*.nro' -o -iname '*.nso' \
    \) | head -n 1)"
    if [ -n "$match" ]; then
      printf '%s\n' "$match"
      return 0
    fi
  fi
  printf '%s\n' "$path"
}

if [ "${1:-}" = "--watch-focus" ]; then
  resolve_steam_app_id || exit 1
  watch_eden_focus
  exit 0
fi

resolve_steam_app_id || exit 1

# Detached from AppImage exec/HUP so the watcher outlives RetroDECK exiting.
if command -v setsid >/dev/null 2>&1; then
  setsid -f "$SELF" --watch-focus >/dev/null 2>&1
else
  nohup "$SELF" --watch-focus >/dev/null 2>&1 &
  disown || true
fi

args=()
prev=""
for arg in "$@"; do
  if [ "$prev" = "-g" ] || [ "$prev" = "--game" ]; then
    args+=("$(resolve_rom "$arg")")
  else
    args+=("$arg")
  fi
  prev="$arg"
done

has_fs=0
for arg in "${args[@]+"${args[@]}"}"; do
  case "$arg" in
    -f|--fullscreen) has_fs=1 ;;
  esac
done
# Append, do not prepend: some AppImage runtimes treat a leading -f as their own flag.
if [ "$has_fs" -eq 0 ]; then
  args+=("-f")
fi

exec "$EDEN_BIN" "${args[@]}"
