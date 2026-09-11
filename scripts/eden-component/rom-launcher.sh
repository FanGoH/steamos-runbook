#!/bin/bash
# Steam/Tender calls this as the shortcut exe, then passes the launch command.
# Huge Switch dumps (Engage) must not start RetroDECK's KDE Flatpak — that
# plus Eden's 8GB guest DRAM is what SteamOS earlyoom SIGTERMs. Exec the
# host AppImage -f -g after pinning 4GB on the Engage custom ini.
set -euo pipefail

HOST_EDEN_APPIMAGE="${EDEN_APPIMAGE:-${HOME}/AppImages/eden.appimage}"
# 6GiB: MK8 (6.77G) sat in RetroDECK's KDE Flatpak, crashed at PC=0, and
# Steam stayed on Launching. 8GiB only caught Engage/Xenoblade (~15G).
HOST_EDEN_MIN_BYTES=$((6 * 1024 * 1024 * 1024))
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
  resolved="$(python3 "$lo_py" --launch-options-for-appid "$appid")" || {
    echo "rom-launcher: no launch command for SteamAppId=$appid" >&2
    exit 1
  }
  echo "rom-launcher: empty LaunchOptions, SteamAppId=$appid -> $resolved" >&2
  # Tender/Steam LaunchOptions are a single shell-quoted command line.
  eval set -- "$resolved"
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
    export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x1209/0xE301,0x1209/0xE302"
    export SDL_JOYSTICK_BLACKLIST_DEVICES_EXCEPT="0x1209/0xE301,0x1209/0xE302"
    export SDL_JOYSTICK_BLACKLIST_DEVICES="0x1209/0x0003"
    ini="${XDG_CONFIG_HOME}/eden/qt-config.ini"
    if [ -f "$PLAYBOOK/scripts/bind-gamepad.py" ]; then
      python3 "$PLAYBOOK/scripts/bind-gamepad.py" apply --emu eden --force >/dev/null 2>&1 || true
    elif [ -f "$ini" ] && [ -f "$PATCHER" ]; then
      python3 "$PATCHER" "$ini" || true
    fi
    echo "rom-launcher: ${bytes} byte Switch dump, host Eden -f -g (no RetroDECK)" >&2
    if [ -x "$PLAYBOOK/scripts/start-emu-steam-ui-inhibit.sh" ]; then
      "$PLAYBOOK/scripts/start-emu-steam-ui-inhibit.sh" >/dev/null 2>&1 || true
    fi
    # RetroDECK does not copy the cart into RAM. Same inode, bind-mounted.
    # RSS is Eden: global 8GB guest DRAM + cart working set. Pin 4GB
    # (Engage's custom 4GB was ignored via use_global=true).
    # Swap is already 7.3G zram + 1G file; host -g still exhausted it.
    # -g is the same BootGame as clicking the list; Eden runs it in the
    # MainWindow constructor before show(), which is why Steam sits on
    # Launching. No second-instance IPC to delay that.
    # Pin 4GB only for Engage. MK8 (0100152000022000) must stay 8GB /
    # 64-bit; --pin-4gb forced 32-bit and ExceptionRaised at 0x0.
    engage_custom="${XDG_CONFIG_HOME}/eden/custom/0100A6301214E000.ini"
    if [ -f "$engage_custom" ] && [ -f "$PATCHER" ]; then
      python3 "$PATCHER" --pin-4gb "$engage_custom" || true
    fi
    exec env DESKTOPINTEGRATION=1 "$HOST_EDEN_APPIMAGE" -f -g "$rom"
  fi
fi

# Insert Flatpak --env after `run` so the sandbox sees CEMU_GAMEMODE_DS.
# Must run at script scope (`set --` in a function only changes that frame).
enable_cemu_gamemode_ds() {
  export CEMU_GAMEMODE_DS=1
  CEMU_DS_NEW_ARGS=()
  local injected=0 arg
  for arg in "$@"; do
    CEMU_DS_NEW_ARGS+=("$arg")
    if [ "$injected" -eq 0 ] && [ "$arg" = "run" ]; then
      CEMU_DS_NEW_ARGS+=(--env=CEMU_GAMEMODE_DS=1)
      injected=1
    fi
  done
}

# Steam RunGame does not inherit CEMU_GAMEMODE_DS. The dual-screen script
# touches logs/cemu-gamemode-ds.want immediately before Play; consume it
# here (and pass --env into Flatpak) so windowed GamePad launch works.
# Delete after read so a leftover file cannot turn the next tile Play
# into windowed 10x10 (spinning logo).
want="${CEMU_GAMEMODE_DS_FLAG:-$PLAYBOOK/logs/cemu-gamemode-ds.want}"
if [ -f "$want" ]; then
  want_mtime="$(stat -c %Y "$want" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  if [ $((now - want_mtime)) -lt 120 ]; then
    enable_cemu_gamemode_ds "$@"
    set -- "${CEMU_DS_NEW_ARGS[@]}"
  fi
  rm -f "$want"
fi

# Wii U / Cemu: gamescope leaves Cemu as a 10x10 InputOnly stub unless
# FOCUSED_APP + STEAM_GAME + FOCUS_DISPLAY=1 are set *before* gtk_init.
# Dual-stream is windowed on :0; do not hammer FOCUS_DISPLAY=1.
# The RetroDECK wrapper also starts this helper; a second start is a no-op.
is_cemu=0
for arg in "$@"; do
  case "$arg" in
    *EMULATOR_CEMU*|*Cemu-wrapper*|*.wux|*.WUX|*.wud|*.WUD|*.wua|*.WUA)
      is_cemu=1
      ;;
    */wiiu/*|*/wii-u/*|*/WiiU/*)
      is_cemu=1
      ;;
  esac
done
# Live :48200 dual-stream (BUSY + gamescope-virtual sidecar): windowed
# GamePad instead of HDMI-only -f. Cemu-wrapper starts --attach.
if [ "$is_cemu" -eq 1 ] && [ "${CEMU_GAMEMODE_DS:-}" != 1 ]; then
  stream_chk="$PLAYBOOK/scripts/gamemode-second-screen-streaming.sh"
  if [ -x "$stream_chk" ] && "$stream_chk"; then
    echo "rom-launcher: :48200 second screen BUSY — CEMU_GAMEMODE_DS=1" >&2
    enable_cemu_gamemode_ds "$@"
    set -- "${CEMU_DS_NEW_ARGS[@]}"
  fi
fi

if [ "$is_cemu" -eq 1 ] && [ -x "$PLAYBOOK/scripts/cemu-gamescope-focus.sh" ]; then
  echo "rom-launcher: host cemu-gamescope-focus SteamAppId=${SteamAppId:-2374129079} DS=${CEMU_GAMEMODE_DS:-}" >&2
  CEMU_STEAM_APPID="${SteamAppId:-2374129079}" CEMU_FOCUS_SECONDS="${CEMU_FOCUS_SECONDS:-30}" \
    "$PLAYBOOK/scripts/cemu-gamescope-focus.sh" >/dev/null 2>&1 &
fi

pick_3ds_rom() {
  local dir="$1"
  local match
  match="$(find "$dir" -type f \( -iname '*.3ds' -o -iname '*.cci' -o -iname '*.cxi' \
    -o -iname '*.cia' \) -printf '%s %p\n' 2>/dev/null \
    | sort -nr | awk '{print substr($0, index($0," ")+1); exit}' || true)"
  printf '%s' "${match:-}"
}

is_azahar=0
azahar_rom=""
for arg in "$@"; do
  case "$arg" in
    *EMULATOR_AZAHAR*|*azahar-launcher*|*org.azahar_emu.Azahar*)
      is_azahar=1
      ;;
    *.3ds|*.3DS|*.cci|*.CCI|*.cxi|*.CXI|*.cia|*.CIA)
      is_azahar=1
      if [ -f "$arg" ]; then
        azahar_rom="$arg"
      elif [ -d "$(dirname "$arg")" ]; then
        azahar_rom="$(pick_3ds_rom "$(dirname "$arg")")"
      fi
      ;;
    */3ds/*|*/3DS/*)
      is_azahar=1
      if [ -z "$azahar_rom" ] && [ -d "$arg" ]; then
        azahar_rom="$(pick_3ds_rom "$arg")"
      fi
      ;;
  esac
done

# RetroDECK Azahar is fullscreen stacked. Game Mode dual-stream is standalone
# Flatpak Separate Windows + ffplay onto :2. Replace the tile when :48200
# is streaming the second screen. Local Play (kms FREE) stays RetroDECK.
if [ "$is_azahar" -eq 1 ]; then
  unset SDL_GAMECONTROLLER_IGNORE_DEVICES
  export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="0x1209/0xE301,0x1209/0xE302"
  export SDL_JOYSTICK_BLACKLIST_DEVICES_EXCEPT="0x1209/0xE301,0x1209/0xE302"
  if [ -f "$PLAYBOOK/scripts/bind-gamepad.py" ]; then
    python3 "$PLAYBOOK/scripts/bind-gamepad.py" apply --emu azahar --force >/dev/null 2>&1 || true
  fi
  stream_chk="$PLAYBOOK/scripts/gamemode-second-screen-streaming.sh"
  azahar_ds="$PLAYBOOK/scripts/ensure-azahar-gamemode-dual-screen.sh"
  if [ -x "$stream_chk" ] && [ -x "$azahar_ds" ] && "$stream_chk"; then
    if [ -z "$azahar_rom" ] || [ ! -f "$azahar_rom" ]; then
      echo "rom-launcher: :48200 second screen BUSY but no 3DS dump in argv" >&2
    else
      echo "rom-launcher: :48200 second screen BUSY — standalone Azahar dual-screen $azahar_rom" >&2
      if [ -x "$PLAYBOOK/scripts/start-emu-steam-ui-inhibit.sh" ]; then
        "$PLAYBOOK/scripts/start-emu-steam-ui-inhibit.sh" >/dev/null 2>&1 || true
      fi
      azahar_quit() {
        bash "$azahar_ds" --quit >/dev/null 2>&1 || true
      }
      trap azahar_quit EXIT INT TERM
      env \
        AZAHAR_ROM="$azahar_rom" \
        AZAHAR_PAD_MATCH="${AZAHAR_PAD_MATCH:-Thor}" \
        AZAHAR_STEAM_APPID="${SteamAppId:-${AZAHAR_STEAM_APPID:-2577949069}}" \
        "$azahar_ds"
      while pgrep -x azahar >/dev/null 2>&1; do
        sleep 1
      done
      azahar_quit
      trap - EXIT INT TERM
      exit 0
    fi
  fi
fi

if [ "$is_cemu" -eq 1 ] || [ "$is_azahar" -eq 1 ] || [ "$is_retrodeck" -eq 1 ]; then
  if [ -x "$PLAYBOOK/scripts/start-emu-steam-ui-inhibit.sh" ]; then
    "$PLAYBOOK/scripts/start-emu-steam-ui-inhibit.sh" >/dev/null 2>&1 || true
  fi
fi

exec "$@"
