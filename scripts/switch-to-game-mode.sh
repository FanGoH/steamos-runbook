#!/usr/bin/env bash
# Leave Plasma dual-stream and return to SteamOS Game Mode.
# Keeps sunshine-ds on the shared :48200 host until gamescope starts, then
# steamos-sunshine-ds-teardown.service --stops DS + the KWin helper so kms
# can bind the same port. Does not touch Decky Sunshine.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

bash "$ROOT/scripts/ensure-sunshine-ds.sh" --install-shortcut >/dev/null || true
TEARDOWN="${SUNSHINE_DS_TEARDOWN_SERVICE:-steamos-sunshine-ds-teardown.service}"
if systemctl --user is-enabled "$TEARDOWN" >/dev/null 2>&1; then
  echo "Keeping sunshine-ds until $TEARDOWN frees :${SUNSHINE_DS_PORT:-48200} for kms."
else
  echo "Tearing down sunshine-ds (needed before gamescope; teardown unit missing)."
  bash "$ROOT/scripts/ensure-sunshine-ds.sh" --stop || true
fi

if ! command -v steamosctl >/dev/null 2>&1; then
  echo "steamosctl missing."
  exit 1
fi

echo "Setting default login mode to game."
steamosctl set-default-login-mode game
echo "Switching to Game Mode."
exec steamosctl switch-to-game-mode
