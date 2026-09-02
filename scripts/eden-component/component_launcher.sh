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

# Cemu SteamInput-P1 = "Steam Virtual Gamepad". Overlay means Steam owns
# the physical Xbox; Eden must use the virtual pad. Force this — Steam's
# IGNORE_DEVICES list hides 045e:02ea, so without ALLOW=1 Eden sees nothing.
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0
export SDL_HIDAPI_JOYSTICK=0
# Motherboard LED enumerates as js0 and can steal SDL port 0.
extra_ignore="0x26ce/0x01a2"
if [ -n "${SDL_GAMECONTROLLER_IGNORE_DEVICES:-}" ]; then
  case ",${SDL_GAMECONTROLLER_IGNORE_DEVICES}," in
    *",${extra_ignore},"*|*",0x26CE/0x01A2,"*) ;;
    *) export SDL_GAMECONTROLLER_IGNORE_DEVICES="${SDL_GAMECONTROLLER_IGNORE_DEVICES},${extra_ignore}" ;;
  esac
else
  export SDL_GAMECONTROLLER_IGNORE_DEVICES="0x045e/0x02ea,${extra_ignore}"
fi

# Eden overwrites qt-config.ini on exit. Re-apply every launch so player 0
# stays on the Steam virtual pad and the Joy-Con HID driver stays off.
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
