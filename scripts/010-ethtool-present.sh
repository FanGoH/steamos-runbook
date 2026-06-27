#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "$ROOT/.env"
set +a

if command -v ethtool >/dev/null 2>&1; then
  echo "ethtool present: $(command -v ethtool)"
  exit 0
fi

echo "ethtool missing."
echo "Run manually:"
echo "  sudo steamos-readonly disable"
echo "  sudo pacman -Sy ethtool"
echo "  sudo steamos-readonly enable"
exit 1
