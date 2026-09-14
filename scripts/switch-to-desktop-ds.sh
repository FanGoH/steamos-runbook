#!/usr/bin/env bash
# From Game Mode: arm proven sunshine-ds, then switch to Plasma.
# Does not launch Cemu/Azahar — those are Moonlight apps on :48100.
# Does not change the default login mode (reboot still Game Mode).
# Requires --yes when gamescope is active (kills Game Mode).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

YES=0
for arg in "$@"; do
  case "$arg" in
    --yes) YES=1 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--yes]" >&2
      exit 2
      ;;
  esac
done

UNIT="${SUNSHINE_DS_ON_DESKTOP_SERVICE:-steamos-sunshine-ds-on-desktop.service}"

if ! command -v steamosctl >/dev/null 2>&1; then
  echo "steamosctl missing."
  exit 1
fi

gamescope_up() {
  systemctl --user is-active gamescope-session.service >/dev/null 2>&1
}

if gamescope_up && [ "$YES" -ne 1 ]; then
  echo "gamescope-session is active. This leaves Game Mode and starts Plasma."
  echo "Re-run with --yes (Decky plugin does that). Agents must not pass --yes."
  exit 2
fi

bash "$ROOT/scripts/ensure-sunshine-ds.sh" --install-shortcut >/dev/null || true

systemctl --user reset-failed "$UNIT" 2>/dev/null || true
if ! systemctl --user start --no-block "$UNIT"; then
  echo "Could not start $UNIT. Run: $ROOT/scripts/ensure-sunshine-ds.sh --install-shortcut"
  exit 1
fi
echo "Armed $UNIT (starts sunshine-ds when Plasma Wayland is up)."

# Default desktop session is plasma.desktop (KWin). Do not set-default-login-mode
# desktop — next boot should stay Game Mode until Moonlight Return to Game Mode.
echo "Switching to desktop mode."
exec steamosctl switch-to-desktop-mode
