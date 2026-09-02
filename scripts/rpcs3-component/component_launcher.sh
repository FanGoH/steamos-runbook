#!/bin/bash
# Bind RPCS3 player 1 to the current pad, then exec RetroDECK's bundled RPCS3.
# Installed to /var/data/retrodeck/external_components/rpcs3/ and as `rpcs3`
# on PATH so %EMULATOR_RPCS3% (systempath `rpcs3`) hits this before the
# bundled component_launcher.sh.
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009"

yml="${XDG_CONFIG_HOME:-${HOME}/.config}/rpcs3/input_configs/global/Default.yml"
patcher="$here/patch-rpcs3-input.py"
if [ -f "$yml" ] && [ -f "$patcher" ]; then
  python3 "$patcher" "$yml" || true
fi

exec /app/retrodeck/components/rpcs3/bin/rpcs3 "$@"
