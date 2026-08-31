#!/usr/bin/env bash
# User-timer entrypoint. Do not enable app-dev.lizardbyte.app.Sunshine.service.
# Decky Sunshine remains the only process starter; this only re-asks Decky
# when GameStream is down (Pulse boot race, PluginLoader restart, crash).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

mkdir -p "$ROOT/logs"

if sunshine_systemd_enabled || sunshine_systemd_active; then
  echo "$(date -Iseconds) Flatpak Sunshine user unit is on; running ensure-sunshine.sh"
  SKIP_MANUAL_SUMMARY=1 exec "$ROOT/scripts/ensure-sunshine.sh"
fi

state="$(sunshine_serverinfo_state 2>/dev/null || true)"
if [ "$state" = "FREE" ]; then
  exit 0
fi
if [ "$state" = "BUSY" ] && sunshine_stream_udp_up; then
  exit 0
fi

if [ -z "$state" ] || [ "$state" = "DOWN" ] || [ "$state" = "UNKNOWN" ]; then
  last_run="$(sunshine_decky_last_run_state 2>/dev/null || echo missing)"
  if [ "$last_run" = "stop" ]; then
    echo "$(date -Iseconds) GameStream down and Decky lastRunState=stop; not starting"
    exit 0
  fi
fi

echo "$(date -Iseconds) GameStream ${state:-DOWN}; running ensure-sunshine.sh"
SKIP_MANUAL_SUMMARY=1 exec "$ROOT/scripts/ensure-sunshine.sh"
