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

ini="${XDG_CONFIG_HOME:-${HOME}/.config}/Cemu/controllerProfiles/controller0.xml"
patcher="$here/patch-cemu-input.py"
if [ -f "$ini" ] && [ -f "$patcher" ]; then
  python3 "$patcher" "$ini" || true
fi

settings="${XDG_CONFIG_HOME:-${HOME}/.config}/Cemu/settings.xml"
if [ -f "$settings" ]; then
  sed -i \
    -e 's|<fullscreen>false</fullscreen>|<fullscreen>true</fullscreen>|' \
    -e 's|<fullscreen_menubar>true</fullscreen_menubar>|<fullscreen_menubar>false</fullscreen_menubar>|' \
    "$settings"
fi

args=("$@")
has_fs=0
for arg in "${args[@]+"${args[@]}"}"; do
  case "$arg" in
    -f|--fullscreen) has_fs=1 ;;
  esac
done
if [ "$has_fs" -eq 0 ]; then
  args+=("-f")
fi

exec /app/retrodeck/components/cemu/component_launcher.sh "${args[@]}"
