#!/bin/sh
# Steam Game Mode tile for Kimochi. Do not exec Kimochi under SteamLaunch —
# that makes Kimochi the focused app, SIGSTOPs steam, and kills Guide/QAM.
# Kick the overlay sidecar (steamos-kimochi-overlay.service) and exit so
# Steam drops this shortcut and Trails keeps HDMI.
set -eu

# Steam chdirs to /bin because Exe is /bin/sh. Keep cwd off the system PATH.
case "$(pwd -P 2>/dev/null || pwd)" in
  /bin|/usr/bin) cd "${HOME:-/home/deck}" ;;
esac

PATH="/usr/bin:/bin:${PATH:-}"
export PATH
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

unit="${KIMOCHI_OVERLAY_SERVICE:-steamos-kimochi-overlay.service}"
if ! systemctl --user restart "$unit"; then
  echo "Kimochi overlay unit $unit failed to start. Run scripts/ensure-kimochi.sh" >&2
  exit 1
fi

n=0
while [ "$n" -lt 50 ]; do
  if pgrep -x kimochi >/dev/null 2>&1; then
    echo "Kimochi overlay is up (not a Steam game)." >&2
    exit 0
  fi
  n=$((n + 1))
  sleep 0.1
done
echo "Kimochi overlay did not come up." >&2
exit 1
