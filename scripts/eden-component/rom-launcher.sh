#!/bin/bash
# Steam/Tender calls this as the shortcut exe, then passes the launch command.
# Huge Switch dumps (Engage) must not start RetroDECK's KDE Flatpak — that
# plus Eden's 8GB guest DRAM is what SteamOS earlyoom SIGTERMs. Exec the
# host AppImage -f -g after pinning 4GB on the Engage custom ini.
set -euo pipefail

HOST_EDEN_APPIMAGE="${EDEN_APPIMAGE:-${HOME}/AppImages/eden.appimage}"
HOST_EDEN_MIN_BYTES=$((8 * 1024 * 1024 * 1024))
PLAYBOOK="${STEAMOS_PLAYBOOK:-${HOME}/steamos-playbook}"
PATCHER="$PLAYBOOK/scripts/eden-component/patch-eden-input.py"

pick_switch_rom() {
  local dir="$1"
  local match
  match="$(find "$dir" -type f -iname '*.xci' -printf '%s %p\n' 2>/dev/null \
    | sort -nr | awk '{print substr($0, index($0," ")+1); exit}' || true)"
  if [ -z "${match:-}" ]; then
    match="$(find "$dir" -type f -iname '*.nsp' \
      ! -iname '*DLC*' ! -iname '*Multiplayer Pack*' \
      -printf '%s %p\n' 2>/dev/null \
      | sort -nr | awk '{print substr($0, index($0," ")+1); exit}' || true)"
  fi
  printf '%s' "${match:-}"
}

# Steam Game Mode often wipes shortcut LaunchOptions while it is running, so
# tiles like Xenoblade / Luigi exec this wrap with an empty argv. Recover the
# dump from SteamAppId → shortcuts.vdf AppName → ~/retrodeck/roms/switch/.
if [ "$#" -eq 0 ]; then
  appid=""
  for cand in "${SteamAppId:-}" "${SteamGameId:-}" "${SteamOverlayGameId:-}"; do
    if [ -n "$cand" ] && [ "$cand" != "0" ]; then
      appid="$cand"
      break
    fi
  done
  if [ -z "${appid:-}" ]; then
    echo "rom-launcher: no args and no SteamAppId (empty LaunchOptions)" >&2
    exit 1
  fi
  lo_py="$PLAYBOOK/scripts/eden-component/set-steam-launch-options.py"
  if [ ! -f "$lo_py" ]; then
    echo "rom-launcher: missing $lo_py" >&2
    exit 1
  fi
  resolved="$(python3 "$lo_py" --rom-for-appid "$appid")" || {
    echo "rom-launcher: no Switch dump for SteamAppId=$appid" >&2
    exit 1
  }
  if [ ! -f "$resolved" ]; then
    echo "rom-launcher: SteamAppId=$appid resolved to missing $resolved" >&2
    exit 1
  fi
  echo "rom-launcher: empty LaunchOptions, SteamAppId=$appid -> $resolved" >&2
  set -- flatpak run net.retrodeck.retrodeck -e '%EMULATOR_RYUBING% %ROM%' "$resolved"
fi

rom=""
for arg in "$@"; do
  case "$arg" in
    *.xci|*.XCI|*.nsp|*.NSP|*.rar|*.RAR)
      if [ -f "$arg" ]; then
        rom="$arg"
      elif [ -d "$(dirname "$arg")" ]; then
        rom="$(pick_switch_rom "$(dirname "$arg")")"
      fi
      ;;
    *)
      if [ -z "$rom" ] && [ -d "$arg" ]; then
        rom="$(pick_switch_rom "$arg")"
      fi
      ;;
  esac
done
if [ -n "$rom" ] && [[ "$rom" == *.rar || "$rom" == *.RAR ]]; then
  rom="$(pick_switch_rom "$(dirname "$rom")")"
fi

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
    echo "rom-launcher: ${bytes} byte Switch dump, host Eden -f -g (no RetroDECK)" >&2
    # RetroDECK does not copy the cart into RAM. Same inode, bind-mounted.
    # RSS is Eden: global 8GB guest DRAM + cart working set. Pin 4GB
    # (Engage's custom 4GB was ignored via use_global=true).
    # Swap is already 7.3G zram + 1G file; host -g still exhausted it.
    # -g is the same BootGame as clicking the list; Eden runs it in the
    # MainWindow constructor before show(), which is why Steam sits on
    # Launching. No second-instance IPC to delay that.
    engage_custom="${XDG_CONFIG_HOME}/eden/custom/0100A6301214E000.ini"
    if [ -f "$engage_custom" ] && [ -f "$PATCHER" ]; then
      python3 "$PATCHER" --pin-4gb "$engage_custom" || true
    fi
    exec env DESKTOPINTEGRATION=1 "$HOST_EDEN_APPIMAGE" -f -g "$rom"
  fi
fi

exec "$@"
