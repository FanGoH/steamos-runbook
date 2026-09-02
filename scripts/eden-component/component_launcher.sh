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
