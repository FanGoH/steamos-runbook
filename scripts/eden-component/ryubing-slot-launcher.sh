#!/bin/bash
# RetroDECK's bundled Switch default is %EMULATOR_RYUBING%. Steam/Tender
# shortcuts that omit -e (plain `flatpak run net.retrodeck.retrodeck %ROM%`)
# hit that. This box has no Ryubing — run the Eden component instead.
set -euo pipefail
here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec "$here/../eden/component_launcher.sh" "$@"
