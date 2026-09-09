#!/usr/bin/env bash
# Sunshine-ds Moonlight app: tear down dual-stream and return to Game Mode.
# sunshine-ds runs in Distrobox and will die during --stop, so systemd-run
# the real switch on the host and exit quickly.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/sunshine-app-common.sh
source "$ROOT/scripts/sunshine-app-common.sh"
reexec_on_host "$ROOT/scripts/sunshine-app-game-mode.sh" "$@"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
UNIT="steamos-return-to-game-mode.service"
SWITCH="$ROOT/scripts/switch-to-game-mode.sh"

systemctl --user stop "$UNIT" 2>/dev/null || true
systemctl --user reset-failed "$UNIT" 2>/dev/null || true

# Delay so this Moonlight app can exit and DS can drop the session before --stop.
if ! systemd-run --user --collect --no-block --unit="${UNIT%.service}" \
  --property=TimeoutStartSec=90 \
  --property=Environment=XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}" \
  /bin/bash -lc "sleep 2; exec '$SWITCH'"; then
  echo "systemd-run failed; running switch in the background."
  nohup bash -lc "sleep 2; exec '$SWITCH'" >>"$ROOT/logs/sunshine-app-game-mode.log" 2>&1 &
  disown || true
fi

echo "Return to Game Mode armed. Moonlight will disconnect; gamescope comes back."
exit 0
