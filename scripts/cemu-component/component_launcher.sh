#!/bin/bash
# User-side Cemu wrapper: bind player 0 to the current pad, then run RetroDECK's
# bundled Cemu. Installed to
# /var/data/retrodeck/external_components/cemu/component_launcher.sh
# and as Cemu-wrapper on PATH so Steam/Tender `-e "%EMULATOR_CEMU%"` hits this
# (run_game.sh uses bundled find-rules; Cemu-wrapper is a systempath entry).
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Steam hides every Xbox ID, including Sunshine's ghost pad. Allow the
# virtual pad (the wrapped held controller) plus Xbox / Switch Pro so a
# Moonlight-only session can still bind Sunshine when Steam virtual is gone.
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009"
# Sunshine always injects a 1209:0003 mouse. Cemu lists it as player-0 and
# GamePad sticks go there (inverted Y). IGNORE_DEVICES_EXCEPT does not hide
# joysticks; blacklist the mouse on both hints.
export SDL_JOYSTICK_BLACKLIST_DEVICES="0x1209/0x0003"
# Agent/SSH SteamLaunch never becomes the gamescope focused app (BPM
# resets FOCUSED_APP=769), so Cemu stays an InputOnly 10x10 stub. A want
# file lets steam://rungameid take focus while keeping dual-stream (no -f).
WANT="${CEMU_GAMEMODE_DS_FLAG:-/home/deck/steamos-playbook/logs/cemu-gamemode-ds.want}"
if [ -z "${CEMU_GAMEMODE_DS:-}" ] && [ -f "$WANT" ]; then
  export CEMU_GAMEMODE_DS=1
fi
if [ "${CEMU_GAMEMODE_DS:-}" = 1 ]; then
  export SDL_GAMECONTROLLER_IGNORE_DEVICES="0x1209/0x0003"
  # Steam injects gamescope WSI; Cemu then deadlocks on an InputOnly 10x10
  # window and never opens /dev/dri. Dual-stream needs normal X11/Vulkan.
  unset ENABLE_GAMESCOPE_WSI
  unset GAMESCOPE_DISPLAY_DISABLED
  export QT_QPA_PLATFORM=xcb
  export GDK_BACKEND=x11
  export SDL_VIDEODRIVER=x11
  # RetroDECK's inner launch drops SteamAppId. gamescope then keeps BPM
  # (769) and Cemu stays a 10x10 InputOnly stub.
  appid="${SteamAppId:-}"
  if [ -z "$appid" ] && [ -f "$WANT" ]; then
    appid="$(head -n1 "$WANT" | tr -d '[:space:]')"
  fi
  appid="${appid:-2374129079}"
  export SteamAppId="$appid"
  export SteamGameId="${SteamGameId:-$appid}"
  export SteamOverlayGameId="${SteamOverlayGameId:-$appid}"
  sdlmap="${CEMU_GAMEMODE_SDLMAP:-/home/deck/steamos-playbook/logs/cemu-gamemode-ds.sdlmap}"
  if [ -f "$sdlmap" ]; then
    # Override community db "Xbox 360 EasySMX" for 045e:028e.
    export SDL_GAMECONTROLLERCONFIG="$(cat "$sdlmap")"
  fi
fi

ini="${XDG_CONFIG_HOME:-${HOME}/.config}/Cemu/controllerProfiles/controller0.xml"
patcher="$here/patch-cemu-input.py"
# Game Mode dual-stream already bound the Sunshine pad as Wii U GamePad.
# The Eden pick order prefers Steam virtual 28de:11ff and would undo that.
if [ "${CEMU_GAMEMODE_DS:-}" != 1 ] && [ -f "$ini" ] && [ -f "$patcher" ]; then
  python3 "$patcher" "$ini" || true
fi

settings="${XDG_CONFIG_HOME:-${HOME}/.config}/Cemu/settings.xml"
if [ -f "$settings" ]; then
  if [ "${CEMU_GAMEMODE_DS:-}" = 1 ]; then
    # Game Mode dual-stream: TV window on session gamescope, GamePad View mapped
    # so it can be mirrored to headless DISPLAY=:2. Do not force -f.
    sed -i \
      -e 's|<fullscreen>true</fullscreen>|<fullscreen>false</fullscreen>|' \
      -e 's|<open_pad>false</open_pad>|<open_pad>true</open_pad>|' \
      -e 's|<fullscreen_menubar>true</fullscreen_menubar>|<fullscreen_menubar>false</fullscreen_menubar>|' \
      "$settings"
  else
    sed -i \
      -e 's|<fullscreen>false</fullscreen>|<fullscreen>true</fullscreen>|' \
      -e 's|<open_pad>true</open_pad>|<open_pad>false</open_pad>|' \
      -e 's|<fullscreen_menubar>true</fullscreen_menubar>|<fullscreen_menubar>false</fullscreen_menubar>|' \
      "$settings"
  fi
fi

args=("$@")
if [ "${CEMU_GAMEMODE_DS:-}" = 1 ]; then
  stripped=()
  for arg in "${args[@]+"${args[@]}"}"; do
    case "$arg" in
      -f|--fullscreen) continue ;;
    esac
    stripped+=("$arg")
  done
  args=("${stripped[@]+"${stripped[@]}"}")
else
  has_fs=0
  for arg in "${args[@]+"${args[@]}"}"; do
    case "$arg" in
      -f|--fullscreen) has_fs=1 ;;
    esac
  done
  if [ "$has_fs" -eq 0 ]; then
    args+=("-f")
  fi
fi

exec /app/retrodeck/components/cemu/component_launcher.sh "${args[@]}"
