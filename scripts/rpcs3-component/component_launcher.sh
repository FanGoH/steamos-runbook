#!/bin/bash
# Bind RPCS3 player 1 to the current pad, then exec RetroDECK's bundled RPCS3.
# Installed to /var/data/retrodeck/external_components/rpcs3/ and as `rpcs3`
# on PATH so %EMULATOR_RPCS3% (systempath `rpcs3`) hits this before the
# bundled component_launcher.sh.
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# SDL3 (RetroDECK RPCS3) ignores 28de:11ff unless this is in the *environment*,
# not only SDL_SetHint. With it, that pad is named Xbox One S Controller (not
# Steam Virtual Gamepad). Binding the SDL2 name creates an empty Sixaxis.
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
unset SDL_GAMEPAD_IGNORE_DEVICES
# Prefer the Steam-wrapped held pad. Include Sunshine only when that pad is gone
# so SDL-0 is not the empty Moonlight ghost during local play.
except="0x28de/0x11ff,0x045e/0x028e,0x045e/0x02fd,0x045e/0x0b13,0x057e/0x2009"
if ! grep -qx 28de /sys/class/input/js*/device/id/vendor 2>/dev/null; then
  except="${except},0x045e/0x02ea"
fi
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$except"

yml="${XDG_CONFIG_HOME:-${HOME}/.config}/rpcs3/input_configs/global/Default.yml"
patcher="$here/patch-rpcs3-input.py"
if [ -f "$yml" ] && [ -f "$patcher" ]; then
  python3 "$patcher" "$yml" || true
fi
# So a skipped wrapper vs a bad Device string is obvious in the next log.
if [ -f "$yml" ]; then
  grep -E '^  Device:' "$yml" | head -1 >&2 || true
fi

exec /app/retrodeck/components/rpcs3/bin/rpcs3 "$@"
