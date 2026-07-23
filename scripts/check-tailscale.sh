#!/usr/bin/env bash
# Check Tailscale status. Do not auto-login; print the exact up command when logged out.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if [ ! -x "$TAILSCALE_BIN" ] && ! command -v tailscale >/dev/null 2>&1; then
  echo "Tailscale not installed (expected deck-tailscale at $TAILSCALE_BIN)."
  record_manual "Install Tailscale via deck-tailscale" <<'EOF'
cd ~/deck-tailscale
sudo bash tailscale.sh
source /etc/profile.d/tailscale.sh
EOF
  exit 1
fi

TS="${TAILSCALE_BIN}"
if [ ! -x "$TS" ]; then
  TS="$(command -v tailscale)"
fi

if "$TS" status >/dev/null 2>&1; then
  echo "Tailscale connected."
  "$TS" status 2>/dev/null | head -5
  exit 0
fi

echo "Tailscale is installed but not logged in or not running."
if [ -z "${TAILSCALE_LOGIN_SERVER:-}" ]; then
  record_manual "Set TAILSCALE_LOGIN_SERVER in .env, then re-login Tailscale" <<EOF
# Copy from .env.example and set your Headscale URL, then:
$(tailscale_up_command)
EOF
else
  record_manual "Re-login Tailscale to Headscale (do not use --ssh yet)" <<EOF
$(tailscale_up_command)
EOF
fi

exit 2
