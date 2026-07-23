#!/usr/bin/env bash
# Check Decky Loader. Do not auto-install; print the official installer command.
# SteamOS updates often remove Decky from Game Mode even when ~/homebrew remains.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

HOMEBREW_DIR="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}"
INSTALL_CMD='curl -L https://github.com/SteamDeckHomebrew/decky-installer/releases/latest/download/install_release.sh | sh'

decky_present=0
if [ -d "$HOMEBREW_DIR" ] || [ -e "$HOMEBREW_DIR/services/PluginLoader" ]; then
  decky_present=1
fi

if [ "$decky_present" -eq 1 ]; then
  echo "Decky homebrew tree present at $HOMEBREW_DIR"
  if [ "${DECKY_REMIND_REINSTALL:-0}" = "1" ]; then
    record_manual "Verify Decky in Game Mode (often broken after SteamOS update)" <<EOF
# If the Decky menu is missing, re-run the official installer:
$INSTALL_CMD
# Then switch back to Game Mode and check Quick Access / the Decky tab.
EOF
  fi
  exit 0
fi

echo "Decky Loader not detected under $HOMEBREW_DIR"
record_manual "Install Decky Loader (manual; do not auto-run)" <<EOF
$INSTALL_CMD
# Enter your sudo password when prompted, then return to Game Mode.
EOF
exit 2
