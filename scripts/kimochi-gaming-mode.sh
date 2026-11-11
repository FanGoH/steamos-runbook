#!/bin/sh
# Steam Game Mode launches Kimochi as a non-Steam shortcut whose Exe is
# /bin/sh. Steam's runtime PATH then omits /usr/bin, so the type2 AppImage
# cannot find fusermount (or bash for AppRun) and exits:
#   Error: No suitable fusermount binary found on the $PATH
#   Cannot mount AppImage
# Prepend host bins, then run Kimochi's own Gaming Mode launcher.
set -eu

# Steam chdirs to /bin because Exe is /bin/sh. Keep cwd off the system PATH.
case "$(pwd -P 2>/dev/null || pwd)" in
  /bin|/usr/bin) cd "${HOME:-/home/deck}" ;;
esac

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

root="${KIMOCHI_GAMING_MODE_ROOT:-${HOME}/.local/share/kimochi/gaming-mode}"
if [ ! -d "$root/current" ]; then
  echo "Kimochi Gaming Mode release missing: $root/current" >&2
  exit 1
fi
release_dir=$(CDPATH= cd -- "$root/current" && pwd -P)
appimage="$release_dir/Kimochi.AppImage"
launcher="$release_dir/scripts/launch-from-steam.sh"

if [ ! -e "$appimage" ]; then
  echo "Kimochi AppImage missing: $appimage" >&2
  exit 1
fi
if [ ! -f "$launcher" ]; then
  echo "Kimochi Gaming Mode launcher missing: $launcher" >&2
  exit 1
fi

# Kimochi 0.8.1 closes the radial menu on this Steam Machine: no Deck hidraw
# makes !deck.connected() true, so every openControllerMenu is cancelled.
# Run a patched copy of the AppDir (ptrace of the live AppImage is blocked).
# Do not rewrite shortcuts.vdf.
self_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
patcher="$self_dir/patch-kimochi-controller-nav.py"
extracted="$root/extracted"
gaming_launcher="$release_dir/scripts/launch-gaming-mode.sh"

# Kimochi is single-instance. A leftover process (debug wrap, previous
# tile) makes Steam's reaper exec AppRun, hand off, and exit in the same
# second — Game Mode shows a crash. Only when this is the Steam shortcut.
stop_stray_kimochi() {
  [ -n "${SteamAppId:-}" ] || return 0
  for pid in $(pgrep -x kimochi 2>/dev/null || true); do
    echo "Kimochi Gaming Mode: replacing leftover pid $pid so Steam can keep the process" >&2
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
  # hookd is a Wine helper; comm is truncated. Match the exe path only.
  for dir in /proc/[0-9]*; do
    [ -r "$dir/cmdline" ] || continue
    pid=${dir#/proc/}
    cmd=$(tr '\0' ' ' <"$dir/cmdline" 2>/dev/null || true)
    case "$cmd" in
      *kimochi-hookd*) kill -TERM "$pid" 2>/dev/null || true ;;
    esac
  done
}

# Put an already-running Steam game (Trails, …) back on HDMI after the tile
# launch. Never write a one-id BASELAYER: dropping 769 makes Guide/QAM/Home
# unable to raise Steam. Skip if Steam's own UI (769) is already in front.
yield_to_running_game() {
  own="${KIMOCHI_STEAM_APP_ID:-${SteamAppId:-}}"
  [ -n "$own" ] || return 0
  (
    export DISPLAY="${DISPLAY:-:0}"
    i=0
    while [ "$i" -lt 40 ]; do
      i=$((i + 1))
      sleep 0.25
      pgrep -x kimochi >/dev/null 2>&1 || continue
      front=$(xprop -root GAMESCOPE_FOCUSED_APP 2>/dev/null) || continue
      case "$front" in
        *' = 769'*) exit 0 ;;
      esac
      ids=$(xprop -root GAMESCOPE_FOCUSABLE_APPS 2>/dev/null) || continue
      game=
      for id in $(printf '%s' "$ids" | tr -c '0-9' ' '); do
        [ -n "$id" ] || continue
        [ "$id" = "769" ] && continue
        [ "$id" = "$own" ] && continue
        game=$id
        break
      done
      [ -n "$game" ] || continue
      # Keep Steam (769) on the stack. A lone game id is what killed the Steam menu.
      xprop -root -f GAMESCOPECTRL_BASELAYER_APPID 32c \
        -set GAMESCOPECTRL_BASELAYER_APPID "$game, 769" 2>/dev/null || true
      xprop -root -f GAMESCOPE_FOCUSED_APP 32c -set GAMESCOPE_FOCUSED_APP "$game" 2>/dev/null || true
      xprop -root -f GAMESCOPE_FOCUSED_APP_GFX 32c -set GAMESCOPE_FOCUSED_APP_GFX "$game" 2>/dev/null || true
      exit 0
    done
  ) &
}

ensure_patched_appdir() {
  if [ -x "$extracted/usr/bin/kimochi" ] && [ -f "$extracted/AppRun" ]; then
    return 0
  fi
  if [ ! -e "$appimage" ]; then
    return 1
  fi
  tmp=$(mktemp -d)
  # --appimage-extract writes ./squashfs-root in cwd.
  if ! (CDPATH= cd -- "$tmp" && "$appimage" --appimage-extract); then
    rm -rf "$tmp"
    return 1
  fi
  rm -rf "$extracted"
  mv "$tmp/squashfs-root" "$extracted"
  rmdir "$tmp" 2>/dev/null || rm -rf "$tmp"
  chmod -R u+w "$extracted" 2>/dev/null || true
}

if [ -f "$patcher" ] && ensure_patched_appdir; then
  if /usr/bin/python3 "$patcher" --elf "$extracted/usr/bin/kimochi"; then
    /usr/bin/python3 "$patcher" --prefer-pad || true
    unset LD_PRELOAD
    # Same as vendor launch-from-steam.sh. Steam's game Xwayland is often :1;
    # Kimochi's overlay must be on :0 (HDMI / GAMESCOPE_FOCUSED_* atoms).
    export DISPLAY=:0
    export KIMOCHI_GAMESCOPE_SCALE="${KIMOCHI_GAMESCOPE_SCALE:-1}"
    export KIMOCHI_GAMESCOPE_UI_SCALE="${KIMOCHI_GAMESCOPE_UI_SCALE:-1.5}"
    export KIMOCHI_STEAM_APP_ID="${KIMOCHI_STEAM_APP_ID:-${SteamAppId:-}}"
    # Vendor launch-from-steam.sh sets MANAGED=1 (Kimochi is the Steam app).
    # On this machine it is a sidecar over Trails: MANAGED=1 steals HDMI and
    # turns LS+RS into return-to-game (controller-nav-cancel) instead of the
    # radial menu. Keep SteamAppId so the reaper tracks the process.
    unset KIMOCHI_STEAM_MANAGED
    stop_stray_kimochi
    yield_to_running_game
    if [ -f "$gaming_launcher" ]; then
      exec /bin/sh "$gaming_launcher" "$extracted/AppRun" "$@"
    fi
    exec /bin/sh "$extracted/AppRun" "$@"
  fi
fi

stop_stray_kimochi
exec /bin/sh "$launcher" "$appimage" "$@"
