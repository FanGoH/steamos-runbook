#!/bin/bash
# Steam/Tender calls this as the shortcut exe, then passes the launch command.
# Huge Switch dumps (Engage) must not start RetroDECK's KDE Flatpak — that
# plus Eden is what SteamOS earlyoom SIGTERMs. Exec the host AppImage
# instead, same as standalone Game Mode. Everything else is exec as-is.
set -euo pipefail

HOST_EDEN_APPIMAGE="${EDEN_APPIMAGE:-${HOME}/AppImages/eden.appimage}"
HOST_EDEN_MIN_BYTES=$((8 * 1024 * 1024 * 1024))
PLAYBOOK="${STEAMOS_PLAYBOOK:-${HOME}/steamos-playbook}"
PATCHER="$PLAYBOOK/scripts/eden-component/patch-eden-input.py"

rom=""
for arg in "$@"; do
  case "$arg" in
    *.xci|*.XCI|*.nsp|*.NSP)
      if [ -f "$arg" ]; then
        rom="$arg"
      fi
      ;;
  esac
done

is_retrodeck=0
for arg in "$@"; do
  case "$arg" in
    net.retrodeck.retrodeck) is_retrodeck=1 ;;
  esac
done

if [ "$is_retrodeck" -eq 1 ] \
  && [ -n "$rom" ] \
  && [ -f "$rom" ] \
  && [[ "$rom" == *"/switch/"* ]] \
  && [ -f "$HOST_EDEN_APPIMAGE" ]; then
  bytes="$(stat -c%s "$rom" 2>/dev/null || echo 0)"
  if [ "$bytes" -gt "$HOST_EDEN_MIN_BYTES" ]; then
    export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-${HOME}/.config}"
    export XDG_DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
    export XDG_CACHE_HOME="${XDG_CACHE_HOME:-${HOME}/.cache}"
    export DISABLE_AUTO_UPDATES=1
    export MALLOC_ARENA_MAX=2
    export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
    export SDL_JOYSTICK_HIDAPI=0
    export SDL_HIDAPI_JOYSTICK=0
    unset SDL_GAMECONTROLLER_IGNORE_DEVICES
    export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009"
    ini="${XDG_CONFIG_HOME}/eden/qt-config.ini"
    if [ -f "$ini" ] && [ -f "$PATCHER" ]; then
      python3 "$PATCHER" "$ini" || true
    fi
    echo "rom-launcher: ${bytes} byte Switch dump, open host Eden fullscreen (no -g)" >&2
    # Do not pass -g: that boots the 15G cart immediately and earlyooms.
    # Same AppImage as standalone; -f is borderless (patcher sets
    # fullscreen_mode=0) so Game Mode fills the nested window.
    exec env DESKTOPINTEGRATION=1 "$HOST_EDEN_APPIMAGE" -f
  fi
fi

exec "$@"
