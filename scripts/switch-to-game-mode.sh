#!/usr/bin/env bash
# Leave Plasma dual-stream and return to SteamOS Game Mode.
# Stops sunshine-ds + the KWin virtual output, sets login mode to game,
# then calls steamosctl. Does not touch Decky Sunshine.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

echo "Tearing down sunshine-ds (needed before gamescope)."
bash "$ROOT/scripts/ensure-sunshine-ds.sh" --stop || true

if ! command -v steamosctl >/dev/null 2>&1; then
  echo "steamosctl missing."
  exit 1
fi

echo "Setting default login mode to game."
steamosctl set-default-login-mode game
echo "Switching to Game Mode."
exec steamosctl switch-to-game-mode
