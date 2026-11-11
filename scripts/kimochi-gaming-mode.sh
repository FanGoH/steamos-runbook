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
    export KIMOCHI_STEAM_MANAGED=1
    if [ -f "$gaming_launcher" ]; then
      exec /bin/sh "$gaming_launcher" "$extracted/AppRun" "$@"
    fi
    exec /bin/sh "$extracted/AppRun" "$@"
  fi
fi

exec /bin/sh "$launcher" "$appimage" "$@"
