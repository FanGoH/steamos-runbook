#!/bin/bash
# User-side RetroDECK component launcher for Eden.
# Installed to /var/data/retrodeck/external_components/eden/ (Flatpak XDG_DATA_HOME).
# Must stay inside the RetroDECK sandbox — do not flatpak-spawn --host.
set -euo pipefail

component_path="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Reuse the host Eden config/keys/NAND that already work. Absolute paths in
# qt-config.ini point at ~/.local/share/eden; XDG must match.
export XDG_CONFIG_HOME="${EDEN_XDG_CONFIG_HOME:-${HOME}/.config}"
export XDG_DATA_HOME="${EDEN_XDG_DATA_HOME:-${HOME}/.local/share}"
export XDG_CACHE_HOME="${EDEN_XDG_CACHE_HOME:-${HOME}/.cache}"

# Steam's IGNORE_DEVICES list hides every Xbox ID. Moonlight/Sunshine
# injects an Xbox-like pad on those IDs after it tears down Steam's
# virtual controller — inheriting the list leaves Eden with nothing.
# Do not keep Steam's list. Allow Steam virtual + Xbox + Sunshine x360;
# that also drops the ASRock LED on js0.
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
# Allow the pads this box actually uses. Player 0's GUID is chosen at
# launch from whichever of these is currently present.
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009"

# Bind player 0 to the pad that is plugged in right now (Sunshine/Xbox
# over Steam virtual). If none yet, keep the last GUID.
ini="${XDG_CONFIG_HOME}/eden/qt-config.ini"
patcher="$component_path/patch-eden-input.py"
if [ -f "$ini" ] && [ -f "$patcher" ]; then
  python3 "$patcher" "$ini" || true
fi

# AppRun's wayland-is-broken hook forces xcb; keep that for Game Mode.
args=()
prev=""
for arg in "$@"; do
  if [ "$prev" = "-g" ] || [ "$prev" = "--game" ]; then
    if [ -d "$arg" ]; then
      match="$(find "$arg" -maxdepth 1 -type f \( \
        -iname '*.xci' -o -iname '*.nsp' -o -iname '*.nca' -o -iname '*.nro' -o -iname '*.nso' \
      \) | head -n 1 || true)"
      args+=("${match:-$arg}")
    else
      args+=("$arg")
    fi
  else
    args+=("$arg")
  fi
  prev="$arg"
done

has_game=0
has_fs=0
for arg in "${args[@]+"${args[@]}"}"; do
  case "$arg" in
    -g|--game) has_game=1 ;;
    -f|--fullscreen) has_fs=1 ;;
  esac
done

# Official ES-DE line is `%EMULATOR_EDEN% %ROM%` with no -g.
if [ "$has_game" -eq 0 ] && [ "${#args[@]}" -ge 1 ]; then
  case "${args[0]}" in
    -*) ;;
    *)
      rom="${args[0]}"
      args=("-g" "$rom" "${args[@]:1}")
      ;;
  esac
fi

# Append, do not prepend: some AppImage stubs treat a leading -f as their own flag.
if [ "$has_fs" -eq 0 ]; then
  args+=("-f")
fi

if [ -x "$component_path/AppRun" ]; then
  exec "$component_path/AppRun" "${args[@]}"
fi
if [ -x "$component_path/bin/eden" ]; then
  exec "$component_path/bin/eden" "${args[@]}"
fi

echo "Eden component binary missing in $component_path" >&2
exit 1
