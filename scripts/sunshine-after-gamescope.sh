#!/usr/bin/env bash
# After Game Mode starts: chmod Pulse, then Decky-restart Sunshine so KMS
# rebinds to gamescope. A Desktop (KWin) session leaves the existing instance
# unable to find monitor 0 — Moonlight hangs then 503s. Not /api/restart.
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

if ! sunshine_pluginloader_ready; then
  log "PluginLoader not answering yet (${DECKY_LOADER_URL})"
  if sunshine_wait_for_pluginloader; then
    log "PluginLoader is up"
    sunshine_open_pulse_dir || true
  else
    log "PluginLoader still down after wait — systemd will retry"
    exit 1
  fi
fi

last_run="$(sunshine_decky_last_run_state 2>/dev/null || echo missing)"
if [ "$last_run" = "stop" ]; then
  log "Decky lastRunState=stop; not restarting"
  exit 0
fi

log "Restarting Sunshine via Decky so KMS binds to gamescope"
if sunshine_restart_via_decky; then
  state="$(sunshine_serverinfo_state 2>/dev/null || true)"
  log "After Decky restart: GameStream ${state:-DOWN}"
  exit 0
fi

log "restart_sunshine failed; systemd will retry"
exit 1
