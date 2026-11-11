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

exec /bin/sh "$launcher" "$appimage" "$@"
