#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if [ "${1:-}" = "--apply" ]; then
  exec "$ROOT/enable-wol.sh"
fi

exec bash "$ROOT/scripts/ensure-wol.sh"
