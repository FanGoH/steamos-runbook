#!/usr/bin/env bash
# Exit 0 when Game Mode sunshine-ds-kms is streaming the second screen.
#
# Tender Cemu Play calls this so a live Thor/Odin dual-stream launches
# windowed GamePad (CEMU_GAMEMODE_DS=1) instead of HDMI-only -f.
#
# True when:
#   - :48200 /serverinfo is SUNSHINE_SERVER_BUSY (ignore :47989 / :48100)
#   - $XDG_RUNTIME_DIR/sunshine-ds-gamemode-virtual has serial= and pw_node=
#     (host path /run/user/<uid>/… — Flatpak XDG_RUNTIME_DIR is a subdir)
# Do not hardcode uniqueid. Sidecar existing without BUSY is idle :2 only.
set -euo pipefail

uid="$(id -u)"
# Sandbox XDG_RUNTIME_DIR is often /run/user/<uid>/app/<flatpak-id>.
SIDECAR="${SUNSHINE_DS_GAMESCOPE_VIRTUAL_FILE:-/run/user/${uid}/sunshine-ds-gamemode-virtual}"
KMS_URL="${SUNSHINE_DS_KMS_URL:-http://127.0.0.1:48200}"

xml="$(curl -sS --max-time 3 "${KMS_URL}/serverinfo" 2>/dev/null || true)"
if ! printf '%s' "$xml" | grep -q 'SUNSHINE_SERVER_BUSY'; then
  exit 1
fi

if [ ! -f "$SIDECAR" ]; then
  exit 1
fi

if ! grep -q '^serial=' "$SIDECAR"; then
  exit 1
fi
if ! grep -qE '^(pw_node|x11)=' "$SIDECAR"; then
  exit 1
fi

exit 0
