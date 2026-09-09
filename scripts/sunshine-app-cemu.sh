#!/usr/bin/env bash
# Sunshine-ds Moonlight app: bind the GameStream pad, launch standalone Cemu
# with Wii U GamePad dual-screen settings, place TV/GamePad, then wait until
# Cemu exits so the session stays BUSY.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/sunshine-app-common.sh
source "$ROOT/scripts/sunshine-app-common.sh"
reexec_on_host "$ROOT/scripts/sunshine-app-cemu.sh"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export CEMU_ALLOW_LIBRARY="${CEMU_ALLOW_LIBRARY:-1}"
mkdir -p "$ROOT/logs"

if ! wait_for_sunshine_pad Sunshine "${SUNSHINE_APP_PAD_WAIT:-45}"; then
  echo "No Sunshine pad yet; binding after Cemu starts may still work."
fi

if ! bash "$ROOT/scripts/ensure-cemu-dual-screen.sh"; then
  echo "ensure-cemu-dual-screen.sh failed. See $ROOT/logs/cemu-dual-screen.log and $ROOT/logs/manual-actions*.txt"
  exit 1
fi

echo "Cemu dual-screen is up; waiting until Cemu exits."
wait_while_comm '^[Cc]emu'
echo "Cemu exited."
exit 0
