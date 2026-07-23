#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if command -v ethtool >/dev/null 2>&1; then
  echo "ethtool present: $(command -v ethtool)"
  exit 0
fi

echo "ethtool missing; ensuring pacman keyrings, then installing..."
bash "$ROOT/scripts/ensure-pacman.sh"

readonly_was="$(steamos_readonly_disable_if_needed)"
set +e
sudo pacman -Sy --noconfirm --needed ethtool
pkg_rc=$?
set -e
steamos_readonly_restore "$readonly_was"

if command -v ethtool >/dev/null 2>&1; then
  echo "ethtool installed: $(command -v ethtool)"
  exit 0
fi

echo "ethtool install failed (pacman exit $pkg_rc)."
record_manual "Install ethtool manually" <<EOF
./scripts/ensure-pacman.sh
sudo steamos-readonly disable
sudo pacman -Sy ethtool
sudo steamos-readonly enable
EOF
exit 1
