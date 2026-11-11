#!/bin/sh
# Kimochi as a Game Mode overlay sidecar — not a Steam-managed game.
# Trails (or whatever is already running) keeps HDMI. Steam's Guide/QAM/Home
# stay on 769. Do not write gamescope focus atoms here.
set -eu

PATH="/usr/bin:/bin:${PATH:-}"
export PATH

if [ -z "${FUSERMOUNT_PROG:-}" ]; then
  if [ -x /usr/bin/fusermount3 ]; then
    FUSERMOUNT_PROG=/usr/bin/fusermount3
  elif [ -x /usr/bin/fusermount ]; then
    FUSERMOUNT_PROG=/usr/bin/fusermount
  fi
  if [ -n "${FUSERMOUNT_PROG:-}" ]; then
    export FUSERMOUNT_PROG
  fi
fi

# Steam's preload and game X server belong to the running game, not us.
unset LD_PRELOAD
unset SteamAppId SteamGameId SteamOverlayGameId
unset KIMOCHI_STEAM_MANAGED KIMOCHI_STEAM_APP_ID

root="${KIMOCHI_GAMING_MODE_ROOT:-${HOME}/.local/share/kimochi/gaming-mode}"
if [ ! -d "$root/current" ]; then
  echo "Kimochi Gaming Mode release missing: $root/current" >&2
  exit 1
fi
release_dir=$(CDPATH= cd -- "$root/current" && pwd -P)
appimage="$release_dir/Kimochi.AppImage"
gaming_launcher="$release_dir/scripts/launch-gaming-mode.sh"
extracted="$root/extracted"
self_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
patcher="$self_dir/patch-kimochi-controller-nav.py"

runtime="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
socket="${KIMOCHI_GAMESCOPE_DISPLAY:-gamescope-0}"
case "$socket" in
  /*) socket_path=$socket ;;
  *) socket_path=$runtime/$socket ;;
esac
n=0
while [ ! -S "$socket_path" ] && [ "$n" -lt 50 ]; do
  n=$((n + 1))
  sleep 0.2
done
if [ ! -S "$socket_path" ]; then
  echo "Gamescope Wayland socket unavailable: $socket_path" >&2
  exit 1
fi

ensure_patched_appdir() {
  if [ -x "$extracted/usr/bin/kimochi" ] && [ -f "$extracted/AppRun" ]; then
    return 0
  fi
  if [ ! -e "$appimage" ]; then
    return 1
  fi
  tmp=$(mktemp -d)
  if ! (CDPATH= cd -- "$tmp" && "$appimage" --appimage-extract); then
    rm -rf "$tmp"
    return 1
  fi
  rm -rf "$extracted"
  mv "$tmp/squashfs-root" "$extracted"
  rmdir "$tmp" 2>/dev/null || rm -rf "$tmp"
  chmod -R u+w "$extracted" 2>/dev/null || true
}

stop_stray_kimochi() {
  for pid in $(pgrep -x kimochi 2>/dev/null || true); do
    echo "Kimochi overlay: replacing leftover pid $pid" >&2
    kill -TERM "$pid" 2>/dev/null || true
  done
  n=0
  while pgrep -x kimochi >/dev/null 2>&1 && [ "$n" -lt 25 ]; do
    n=$((n + 1))
    sleep 0.1
  done
  for pid in $(pgrep -x kimochi 2>/dev/null || true); do
    kill -KILL "$pid" 2>/dev/null || true
  done
  for dir in /proc/[0-9]*; do
    [ -r "$dir/cmdline" ] || continue
    pid=${dir#/proc/}
    cmd=$(tr '\0' ' ' <"$dir/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *kimochi-hookd*) kill -TERM "$pid" 2>/dev/null || true ;;
    esac
  done
}

export DISPLAY="${DISPLAY:-:0}"
export KIMOCHI_GAMESCOPE_SCALE="${KIMOCHI_GAMESCOPE_SCALE:-1}"
export KIMOCHI_GAMESCOPE_UI_SCALE="${KIMOCHI_GAMESCOPE_UI_SCALE:-1.5}"

# Kimochi's gamescope watchdog SIGSTOPs steam on overlay start, which freezes
# Guide/QAM. Keep steam running. Kimochi still reads the Sunshine pad via
# evdev (preferredGamepadIndex). Do not write gamescope focus atoms.
release_steam() {
  (
    n=0
    while [ "$n" -lt 50 ]; do
      pgrep -x kimochi >/dev/null 2>&1 && break
      n=$((n + 1))
      sleep 0.1
    done
    while pgrep -x kimochi >/dev/null 2>&1; do
      for pid in $(ps -eo pid,comm | awk '$2=="kimochi-input"{print $1}'); do
        kill -TERM "$pid" 2>/dev/null || true
      done
      for pid in $(ps -eo pid,stat,comm | awk '$3=="steam" && $2 ~ /T/{print $1}'); do
        kill -CONT "$pid" 2>/dev/null || true
      done
      sleep 0.5
    done
  ) &
}

stop_stray_kimochi
release_steam

if [ -f "$patcher" ] && ensure_patched_appdir; then
  /usr/bin/python3 "$patcher" --elf "$extracted/usr/bin/kimochi" || true
  /usr/bin/python3 "$patcher" --prefer-pad || true
  if [ -f "$gaming_launcher" ]; then
    exec /bin/sh "$gaming_launcher" "$extracted/AppRun" "$@"
  fi
  exec /bin/sh "$extracted/AppRun" "$@"
fi

if [ ! -e "$appimage" ]; then
  echo "Kimochi AppImage missing: $appimage" >&2
  exit 1
fi
if [ ! -f "$gaming_launcher" ]; then
  echo "Kimochi Gaming Mode launcher missing: $gaming_launcher" >&2
  exit 1
fi
exec /bin/sh "$gaming_launcher" "$appimage" "$@"
