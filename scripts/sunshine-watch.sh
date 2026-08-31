#!/usr/bin/env bash
# Session oneshot: make Pulse bind-mountable for Decky's setuid bwrap, then
# start Sunshine via Decky if GameStream is down. Not a poll loop.
# Do not enable app-dev.lizardbyte.app.Sunshine.service.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

mkdir -p "$ROOT/logs"

log() {
  printf '%s\n' "$(date -Iseconds) $*"
}

if sunshine_open_pulse_dir; then
  log "Pulse dir is bind-mountable ($(sunshine_pulse_socket))"
else
  log "Pulse dir not ready yet ($(sunshine_pulse_socket))"
  if sunshine_wait_for_pulse; then
    sunshine_open_pulse_dir || true
    log "Pulse became ready"
  else
    log "Pulse still missing after wait"
  fi
fi

if sunshine_systemd_enabled || sunshine_systemd_active; then
  log "Flatpak Sunshine user unit is on; disabling via ensure-sunshine.sh"
  SKIP_MANUAL_SUMMARY=1 "$ROOT/scripts/ensure-sunshine.sh"
  exit $?
fi

state="$(sunshine_serverinfo_state 2>/dev/null || true)"
if [ "$state" = "FREE" ]; then
  log "GameStream FREE (ok)"
  exit 0
fi
if [ "$state" = "BUSY" ] && sunshine_stream_udp_up; then
  log "GameStream BUSY with live stream UDP (leaving session alone)"
  exit 0
fi

if [ "$state" = "BUSY" ]; then
  log "GameStream DOWN-equivalent: stale BUSY currentgame=$(sunshine_currentgame || echo none) — no stream UDP"
else
  log "GameStream DOWN (${SUNSHINE_GAMESTREAM_URL})"
fi

last_run="$(sunshine_decky_last_run_state 2>/dev/null || echo missing)"
if [ "$last_run" = "stop" ]; then
  log "Decky lastRunState=stop; not starting"
  exit 0
fi

log "Asking Decky to start Sunshine (not systemd, not /api/restart)"
SKIP_MANUAL_SUMMARY=1 "$ROOT/scripts/ensure-sunshine.sh"
rc=$?
state="$(sunshine_serverinfo_state 2>/dev/null || true)"
log "After Decky start: GameStream ${state:-DOWN} ensure-sunshine exit=$rc"
exit "$rc"
