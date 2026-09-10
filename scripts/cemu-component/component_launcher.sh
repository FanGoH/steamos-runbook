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
# gamescope-session exports GAMESCOPE_DISPLAY_DISABLED=1, which leaves
# Cemu UnMapped (spinning Steam logo). Always clear it. gamescope WSI
# deadlocks Cemu on an InputOnly 10x10 window (no /dev/dri) even when
# :0 FOCUSED_APP is already the shortcut — use normal X11/Vulkan.
unset GAMESCOPE_DISPLAY_DISABLED
unset ENABLE_GAMESCOPE_WSI
# Optional bisect: llvmpipe skips gamescope InputOnly GLX.
if [ "${CEMU_SOFTWARE_GL:-}" = 1 ] || [ -f /home/deck/steamos-playbook/logs/cemu-software-gl ]; then
  export LIBGL_ALWAYS_SOFTWARE=1
  export GALLIUM_DRIVER=llvmpipe
fi
# Steam overlay renderer can pin wx/GTK on an InputOnly 10x10 window.
unset LD_PRELOAD
unset LD_PRELOAD_64
unset LD_PRELOAD_32
export QT_QPA_PLATFORM=xcb
export GDK_BACKEND=x11
export SDL_VIDEODRIVER=x11
# Game Mode exports GTK_IM_MODULE=Steam. wxGTK then deadlocks in gtk_init
# (IME waits for a focused game window) and Cemu stays a 10x10 InputOnly stub.
unset GTK_IM_MODULE
export GTK_IM_MODULE=gtk-im-context-simple
export GTK_A11Y=none
export NO_AT_BRIDGE=1
unset GTK_MODULES
unset GTK3_MODULES
export GTK_PATH="${GTK_PATH:-}"
if [ -f "${CEMU_TEST_DISPLAY_FLAG:-/home/deck/steamos-playbook/logs/cemu-test-display}" ]; then
  export DISPLAY="$(cat "${CEMU_TEST_DISPLAY_FLAG:-/home/deck/steamos-playbook/logs/cemu-test-display}")"
fi
# Flatpak+gamescope has hung Cemu in pango/fontconfig before "Init Cemu".
if [ -f "$here/fonts.conf" ]; then
  export FONTCONFIG_FILE="$here/fonts.conf"
fi

# Dual-stream only when the launcher exports CEMU_GAMEMODE_DS=1.
if [ "${CEMU_GAMEMODE_DS:-}" = 1 ]; then
  export SDL_GAMECONTROLLER_IGNORE_DEVICES="0x1209/0x0003"
  appid="${SteamAppId:-2374129079}"
  export SteamAppId="$appid"
  export SteamGameId="${SteamGameId:-$appid}"
  export SteamOverlayGameId="${SteamOverlayGameId:-$appid}"
fi

# Always override community db "Xbox 360 EasySMX" (045e:028e). Cemu reads
# SDL_GameControllerName at startup; the file form survives Flatpak env
# flattening that drops multiline SDL_GAMECONTROLLERCONFIG.
sdlmap="${CEMU_GAMEMODE_SDLMAP:-/home/deck/steamos-playbook/logs/cemu-gamemode-ds.sdlmap}"
if [ -f "$sdlmap" ]; then
  export SDL_GAMECONTROLLERCONFIG_FILE="$sdlmap"
  export SDL_GAMECONTROLLERCONFIG="$(tr '\n' '@' <"$sdlmap" | tr '@' '\n')"
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

# Tender rom-launcher starts cemu-gamescope-focus.sh on the host before
# RetroDECK. A second start here is a no-op unless that helper died.
if [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null \
  && [ -x /home/deck/steamos-playbook/scripts/cemu-gamescope-focus.sh ]; then
  appid="${SteamAppId:-2374129079}"
  flatpak-spawn --host --env="CEMU_STEAM_APPID=$appid" --env="CEMU_FOCUS_SECONDS=30" \
    /home/deck/steamos-playbook/scripts/cemu-gamescope-focus.sh >/dev/null 2>&1 &
fi

# Tender's rom-launcher cwd is homebrew/plugins/romm-tender/bin. Cemu writes
# log.txt / shaderCache relative to cwd; the working boot used data/Cemu.
cemu_data="${XDG_DATA_HOME:-${HOME}/.local/share}/Cemu"
mkdir -p "$cemu_data"
cd "$cemu_data"

# Steam swallows the emulator pipe. Keep a copy so a 10x10 hang is visible.
cemu_log="${CEMU_WRAPPER_LOG:-/home/deck/steamos-playbook/logs/cemu-wrapper.log}"
mkdir -p "$(dirname "$cemu_log")"
{
  echo "---- $(date -Iseconds) DISPLAY=${DISPLAY:-} SteamAppId=${SteamAppId:-} args:${args[*]} ----"
  echo "GTK_IM_MODULE=${GTK_IM_MODULE:-} GDK_BACKEND=${GDK_BACKEND:-} WSI=${ENABLE_GAMESCOPE_WSI:-} DISABLED=${GAMESCOPE_DISPLAY_DISABLED:-}"
} >>"$cemu_log"

exec /app/retrodeck/components/cemu/component_launcher.sh "${args[@]}" >>"$cemu_log" 2>&1
