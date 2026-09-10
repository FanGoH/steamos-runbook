#!/usr/bin/env bash
# Game Mode (:48200) Moonlight app: bind the live Sunshine pad, launch Cemu
# dual-screen, stay BUSY until Cemu exits.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/sunshine-app-common.sh
source "$ROOT/scripts/sunshine-app-common.sh"
reexec_on_host "$ROOT/scripts/sunshine-app-cemu-gamemode.sh"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

mkdir -p "$ROOT/logs"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

if ! wait_for_sunshine_pad Sunshine "${SUNSHINE_APP_PAD_WAIT:-45}"; then
  echo "No Sunshine pad yet; binding after Cemu starts may still work."
fi

export CEMU_PAD_MATCH="${CEMU_PAD_MATCH:-Sunshine}"
if ! bash "$ROOT/scripts/ensure-cemu-gamemode-dual-screen.sh"; then
  echo "ensure-cemu-gamemode-dual-screen.sh failed. See $ROOT/logs/cemu-gamemode-ds.log"
  exit 1
fi

echo "Game Mode Cemu dual-screen is up; waiting until Cemu exits."
wait_while_comm '^[Cc]emu'
bash "$ROOT/scripts/ensure-cemu-gamemode-dual-screen.sh" --stop || true
echo "Cemu exited."
exit 0
