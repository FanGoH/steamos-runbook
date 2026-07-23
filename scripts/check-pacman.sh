#!/usr/bin/env bash
# Read-only pacman keyring status check (used by health-check).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if ! command -v pacman >/dev/null 2>&1; then
  echo "pacman not found on PATH."
  exit 1
fi

if pacman_keyring_ok; then
  echo "pacman keyring looks initialized."
  exit 0
fi

echo "pacman keyring looks broken or uninitialized."
echo "Fix with: ./scripts/ensure-pacman.sh"
exit 2
