#!/usr/bin/env bash
# Check Decky Loader files only. Do not nag to reinstall after updates.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

HOMEBREW_DIR="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}"

if [ -e "$HOMEBREW_DIR/services/PluginLoader" ] || [ -d "$HOMEBREW_DIR" ]; then
  echo "Decky files present at $HOMEBREW_DIR"
  exit 0
fi

echo "Decky files not found under $HOMEBREW_DIR (optional)."
exit 2
