#!/bin/bash
# User-side Cemu wrapper: bind player 0 to the current pad, then run RetroDECK's
# bundled Cemu. Installed to
# /var/data/retrodeck/external_components/cemu/component_launcher.sh
# and as Cemu-wrapper on PATH so Steam/Tender `-e "%EMULATOR_CEMU%"` hits this
# (run_game.sh uses bundled find-rules; Cemu-wrapper is a systempath entry).
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
ini="${XDG_CONFIG_HOME:-${HOME}/.config}/Cemu/controllerProfiles/controller0.xml"
patcher="$here/patch-cemu-input.py"
if [ -f "$ini" ] && [ -f "$patcher" ]; then
  python3 "$patcher" "$ini" || true
fi

exec /app/retrodeck/components/cemu/component_launcher.sh "$@"
