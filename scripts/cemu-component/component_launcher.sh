#!/bin/bash
# User-side Cemu wrapper: bind player 0 to the current pad, then run RetroDECK's
# bundled Cemu. Installed to
# /var/data/retrodeck/external_components/cemu/component_launcher.sh
# and as Cemu-wrapper on PATH so Steam/Tender `-e "%EMULATOR_CEMU%"` hits this
# (run_game.sh uses bundled find-rules; Cemu-wrapper is a systempath entry).
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Steam RunGame does not inherit CEMU_GAMEMODE_DS from the dual-screen
# script. Touch logs/cemu-gamemode-ds.want immediately before RunGame;
# consume it here so a leftover file cannot turn the next Tender Play
# into windowed 10x10 (spinning logo).
want="${CEMU_GAMEMODE_DS_FLAG:-/home/deck/steamos-playbook/logs/cemu-gamemode-ds.want}"
if [ -f "$want" ]; then
  want_mtime="$(stat -c %Y "$want" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  if [ $((now - want_mtime)) -lt 120 ]; then
    export CEMU_GAMEMODE_DS=1
  fi
  rm -f "$want"
fi

# Tender Play while Moonlight is on :48200 video/1: same windowed GamePad
# path as the want file. Helper ignores Decky :47989 and desktop :48100.
if [ "${CEMU_GAMEMODE_DS:-}" != 1 ]; then
  stream_chk="${STEAMOS_PLAYBOOK:-/home/deck/steamos-playbook}/scripts/gamemode-second-screen-streaming.sh"
  if [ -x "$stream_chk" ] && "$stream_chk"; then
    export CEMU_GAMEMODE_DS=1
  fi
fi

# Emulators bind EmuPads P1/P2. Mux copies Sunshine / local / Steam pads.
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x1209/0xE301,0x1209/0xE302"
export SDL_JOYSTICK_BLACKLIST_DEVICES_EXCEPT="0x1209/0xE301,0x1209/0xE302"
# Sunshine always injects a 1209:0003 mouse. EXCEPT hides it from GameController
# but not from the joystick list unless blacklist-except is honored.
export SDL_JOYSTICK_BLACKLIST_DEVICES="0x1209/0x0003"
# gamescope-session exports GAMESCOPE_DISPLAY_DISABLED=1, which leaves
# Cemu UnMapped (spinning Steam logo). Always clear it.
# Tender / Steam Play -f needs ENABLE_GAMESCOPE_WSI so gamescope can hand
# out a nested swapchain once FOCUSED_APP is the shortcut and FOCUS_DISPLAY
# is xwayland 1. Unsetting WSI leaves a 10x10 InputOnly stub forever.
# Dual-stream still drops WSI (windowed x11grab on :0 / :2).
unset GAMESCOPE_DISPLAY_DISABLED
if [ "${CEMU_GAMEMODE_DS:-}" != 1 ]; then
  export ENABLE_GAMESCOPE_WSI="${ENABLE_GAMESCOPE_WSI:-1}"
fi
# Optional bisect: llvmpipe skips gamescope InputOnly GLX.
if [ "${CEMU_SOFTWARE_GL:-}" = 1 ] || [ -f /home/deck/steamos-playbook/logs/cemu-software-gl ]; then
  export LIBGL_ALWAYS_SOFTWARE=1
  export GALLIUM_DRIVER=llvmpipe
fi
export QT_QPA_PLATFORM=xcb
export GDK_BACKEND=x11
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
# FONTCONFIG_FILE pointing at a tiny fonts.conf was added while bisecting
# the 10x10 hang. The live hung process has a stuck "[pango] fontcon"
# thread, so do not force a custom config on Tender Play.
if [ "${CEMU_CUSTOM_FONTCONFIG:-}" = 1 ] && [ -f "$here/fonts.conf" ]; then
  export FONTCONFIG_FILE="$here/fonts.conf"
fi

# Dual-stream only when the launcher exports CEMU_GAMEMODE_DS=1.
if [ "${CEMU_GAMEMODE_DS:-}" = 1 ]; then
  unset ENABLE_GAMESCOPE_WSI
  export SDL_VIDEODRIVER=x11
  unset LD_PRELOAD
  unset LD_PRELOAD_64
  unset LD_PRELOAD_32
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
# Tile decides P1 type: GamePad when the second screen is streamed
# (CEMU_GAMEMODE_DS=1), Pro otherwise. Cemu reads type at start.
playbook="${STEAMOS_PLAYBOOK:-/home/deck/steamos-playbook}"
bind_py="$playbook/scripts/bind-gamepad.py"
if [ "${CEMU_GAMEMODE_DS:-}" = 1 ]; then
  cemu_p1=gamepad
else
  cemu_p1=pro
fi
bind_cemu_p1() {
  if [ -f "$bind_py" ]; then
    if [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null; then
      flatpak-spawn --host --env="CEMU_GAMEMODE_DS=${CEMU_GAMEMODE_DS:-}" \
        python3 "$bind_py" apply --emu cemu --xml "$ini" --force --cemu-p1 "$cemu_p1"
    else
      python3 "$bind_py" apply --emu cemu --xml "$ini" --force --cemu-p1 "$cemu_p1"
    fi
    return
  fi
  if [ -f "$patcher" ]; then
    python3 "$patcher" "$ini" || true
  fi
}

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
# RetroDECK. Dual-stream is windowed but still needs FOCUSED_APP=<shortcut>
# before gtk_init (769 deadlocks pango). The helper must not set HDMI
# BASELAYER to the 10x10 stub.
if [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null \
  && [ -x /home/deck/steamos-playbook/scripts/cemu-gamescope-focus.sh ]; then
  appid="${SteamAppId:-2374129079}"
  flatpak-spawn --host --env="CEMU_STEAM_APPID=$appid" --env="CEMU_FOCUS_SECONDS=30" \
    /home/deck/steamos-playbook/scripts/cemu-gamescope-focus.sh >/dev/null 2>&1 &
fi
if [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null \
  && [ -x /home/deck/steamos-playbook/scripts/start-emu-steam-ui-inhibit.sh ]; then
  flatpak-spawn --host /home/deck/steamos-playbook/scripts/start-emu-steam-ui-inhibit.sh \
    >/dev/null 2>&1 &
fi

# Tender already launched Cemu. --attach waits for GamePad View, ffplay
# onto :2, and a focus watcher that paints the idle clock on exit.
if [ "${CEMU_GAMEMODE_DS:-}" = 1 ] && [ "${CEMU_GAMEMODE_DS_ATTACH:-1}" != 0 ]; then
  attach_sh="${STEAMOS_PLAYBOOK:-/home/deck/steamos-playbook}/scripts/ensure-cemu-gamemode-dual-screen.sh"
  attach_log="${CEMU_WRAPPER_LOG:-/home/deck/steamos-playbook/logs/cemu-wrapper.log}"
  if [ -x "$attach_sh" ]; then
    if [ -n "${FLATPAK_ID:-}" ] && command -v flatpak-spawn >/dev/null; then
      flatpak-spawn --host --env="CEMU_GAMEMODE_DS=1" \
        --env="CEMU_PAD_MATCH=${CEMU_PAD_MATCH:-Thor}" \
        "$attach_sh" --attach >>"$attach_log" 2>&1 &
    else
      env CEMU_GAMEMODE_DS=1 CEMU_PAD_MATCH="${CEMU_PAD_MATCH:-Thor}" \
        "$attach_sh" --attach >>"$attach_log" 2>&1 &
    fi
  fi
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
  echo "---- $(date -Iseconds) DISPLAY=${DISPLAY:-} SteamAppId=${SteamAppId:-} DS=${CEMU_GAMEMODE_DS:-} P1=${cemu_p1:-} args:${args[*]} ----"
  echo "GTK_IM_MODULE=${GTK_IM_MODULE:-} GDK_BACKEND=${GDK_BACKEND:-} WSI=${ENABLE_GAMESCOPE_WSI:-} DISABLED=${GAMESCOPE_DISPLAY_DISABLED:-}"
} >>"$cemu_log"

if [ -f "$ini" ]; then
  bind_cemu_p1 >>"$cemu_log" 2>&1 || true
fi

exec /app/retrodeck/components/cemu/component_launcher.sh "${args[@]}" >>"$cemu_log" 2>&1
