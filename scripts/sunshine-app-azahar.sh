#!/usr/bin/env bash
# Sunshine-ds Moonlight app: bind the GameStream pad, launch standalone Azahar
# with Separate Windows (top HDMI, bottom Virtual-sunshine-ds), then wait until
# Azahar exits so the session stays BUSY.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/sunshine-app-common.sh
source "$ROOT/scripts/sunshine-app-common.sh"
reexec_on_host "$ROOT/scripts/sunshine-app-azahar.sh"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export AZAHAR_ALLOW_LIBRARY="${AZAHAR_ALLOW_LIBRARY:-1}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
export DISPLAY="${DISPLAY:-:0}"
mkdir -p "$ROOT/logs"

# Do not wait for a Sunshine pad — that used to stall Open for up to 45s.
# Leftover Azahar makes ensure skip launch, so Open looks like a no-op.
if ps -eo comm= | grep -Eq '^azahar'; then
  echo "Stopping leftover Azahar so this Moonlight app can boot."
  stop_matching_comm '^azahar'
fi

if ! bash "$ROOT/scripts/ensure-azahar-dual-screen.sh"; then
  echo "ensure-azahar-dual-screen.sh failed. See $ROOT/logs/azahar-dual-screen.log and $ROOT/logs/manual-actions*.txt"
  exit 1
fi

# Library boot creates Primary/Secondary only after a game is chosen. Re-place
# until Azahar exits so those windows fill HDMI + Virtual-sunshine-ds.
place_watch_pid=""
(
  while ps -eo comm= | grep -Eq '^azahar'; do
    bash "$ROOT/scripts/ensure-azahar-dual-screen.sh" --place-only >/dev/null 2>&1 || true
    sleep 1
  done
) &
place_watch_pid=$!

echo "Azahar dual-screen is up; waiting until Azahar exits."
wait_while_comm '^azahar' "$place_watch_pid"
echo "Azahar exited."
exit 0
