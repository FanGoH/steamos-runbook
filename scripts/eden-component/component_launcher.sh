#!/bin/bash
# User-side RetroDECK component launcher for Eden.
# Installed to /var/data/retrodeck/external_components/eden/ (Flatpak XDG_DATA_HOME).
# Small Switch dumps stay in-sandbox (Cemu-style). Dumps over 8GiB (Engage)
# must not -g at all: that faults the cart until earlyoom. Open host Eden
# fullscreen instead (same as the Tender wrap); start the game from the list.
set -euo pipefail

HOST_EDEN_APPIMAGE="${EDEN_APPIMAGE:-${HOME}/AppImages/eden.appimage}"
# 8GiB: 13 Sentinels is ~7.5G (in-sandbox OK); Engage cart is ~15G.
HOST_EDEN_MIN_BYTES=$((8 * 1024 * 1024 * 1024))

component_path="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

# Reuse the host Eden config/keys/NAND that already work. Absolute paths in
# qt-config.ini point at ~/.local/share/eden; XDG must match.
export XDG_CONFIG_HOME="${EDEN_XDG_CONFIG_HOME:-${HOME}/.config}"
export XDG_DATA_HOME="${EDEN_XDG_DATA_HOME:-${HOME}/.local/share}"
export XDG_CACHE_HOME="${EDEN_XDG_CACHE_HOME:-${HOME}/.cache}"
# Extracted AppRun still ships a self-updater that rewrites $APPIMAGE.
export DISABLE_AUTO_UPDATES=1
# Flatpak + a 15G dump otherwise grows glibc arenas until earlyoom.
export MALLOC_ARENA_MAX=2

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

# Bind player 0 to the pad that is plugged in right now (physical Xbox
# / Steam virtual over Sunshine). If none yet, keep the last GUID.
# Also force borderless + async shaders — Exclusive + gamescope is the
# Steam "Launching…" hang that ends in earlyoom SIGTERM on big titles.
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
      # Prefer a cart .xci over tiny DLC .nsp files in the same folder.
      match="$(find "$arg" -maxdepth 1 -type f -iname '*.xci' -printf '%s %p\n' 2>/dev/null \
        | sort -nr | awk '{print substr($0, index($0," ")+1); exit}' || true)"
      if [ -z "${match:-}" ]; then
        match="$(find "$arg" -maxdepth 1 -type f \( \
          -iname '*.nsp' -o -iname '*.nca' -o -iname '*.nro' -o -iname '*.nso' \
        \) -printf '%s %p\n' 2>/dev/null \
          | sort -nr | awk '{print substr($0, index($0," ")+1); exit}' || true)"
      fi
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
filtered=()
for arg in "${args[@]+"${args[@]}"}"; do
  case "$arg" in
    -g|--game) has_game=1; filtered+=("$arg") ;;
    # Standalone Eden in Game Mode works without -f. Forcing it here
    # keeps Steam on Launching until a first frame and is what earlyoom
    # kills on big dumps. Do not add it; strip it if ES-DE passed one.
    -f|--fullscreen) ;;
    *) filtered+=("$arg") ;;
  esac
done
args=("${filtered[@]+"${filtered[@]}"}")

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

eden_rom_path=""
prev=""
for arg in "${args[@]+"${args[@]}"}"; do
  if [ "$prev" = "-g" ] || [ "$prev" = "--game" ]; then
    eden_rom_path="$arg"
  fi
  prev="$arg"
done

eden_rom_bytes=0
if [ -n "$eden_rom_path" ] && [ -f "$eden_rom_path" ]; then
  eden_rom_bytes="$(stat -c%s "$eden_rom_path" 2>/dev/null || echo 0)"
fi

host_exec_eden() {
  local img="$1"
  shift
  local spawn=(flatpak-spawn --host)
  local e
  for e in \
    DISPLAY XDG_RUNTIME_DIR XDG_CONFIG_HOME XDG_DATA_HOME XDG_CACHE_HOME \
    DISABLE_AUTO_UPDATES MALLOC_ARENA_MAX \
    SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD SDL_JOYSTICK_HIDAPI \
    SDL_HIDAPI_JOYSTICK SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT \
    SteamAppId SteamGameId STEAM_OVERLAY GAMESCOPE_WAYLAND_DISPLAY
  do
    if [ -n "${!e:-}" ]; then
      spawn+=(--env="${e}=${!e}")
    fi
  done
  spawn+=(--env=SDL_GAMECONTROLLER_IGNORE_DEVICES=)
  exec "${spawn[@]}" "$img" "$@"
}

if [ "$eden_rom_bytes" -gt "$HOST_EDEN_MIN_BYTES" ]; then
  echo "Eden: dump ${eden_rom_bytes} bytes, open fullscreen UI (no -g)" >&2
  if [ -n "${FLATPAK_ID:-}" ] \
    && command -v flatpak-spawn >/dev/null \
    && [ -f "$HOST_EDEN_APPIMAGE" ]; then
    host_exec_eden "$HOST_EDEN_APPIMAGE" -f
  fi
  if [ -x "$component_path/AppRun" ]; then
    exec "$component_path/AppRun" -f
  fi
  if [ -x "$component_path/bin/eden" ]; then
    exec "$component_path/bin/eden" -f
  fi
fi

if [ -x "$component_path/AppRun" ]; then
  exec "$component_path/AppRun" "${args[@]}"
fi
if [ -x "$component_path/bin/eden" ]; then
  exec "$component_path/bin/eden" "${args[@]}"
fi

echo "Eden component binary missing in $component_path" >&2
exit 1
