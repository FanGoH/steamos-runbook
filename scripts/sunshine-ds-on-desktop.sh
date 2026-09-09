#!/usr/bin/env bash
# Wait for Plasma Wayland after a Game Mode → Desktop switch, then start
# proven sunshine-ds (:48100, capture=kwin). Does not switch sessions.
# Started on demand by the Sunshine DS Decky plugin / switch-to-desktop-ds.sh.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
WAIT_SECS="${SUNSHINE_DS_DESKTOP_WAIT_SECS:-90}"

log() {
  printf '%s %s\n' "$(date -Iseconds)" "$*"
}

wayland_ready() {
  [ -S "${XDG_RUNTIME_DIR}/wayland-0" ] || [ -S "${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY:-wayland-0}" ]
}

gamescope_up() {
  systemctl --user is-active gamescope-session.service >/dev/null 2>&1
}

log "Waiting up to ${WAIT_SECS}s for Plasma Wayland (not gamescope)."
waited=0
while [ "$waited" -lt "$WAIT_SECS" ]; do
  if wayland_ready && ! gamescope_up; then
    log "Wayland is up and gamescope is down."
    exec bash "$ROOT/scripts/ensure-sunshine-ds.sh"
  fi
  sleep 1
  waited=$((waited + 1))
done

log "Plasma Wayland did not appear in ${WAIT_SECS}s (wayland=$(wayland_ready && echo yes || echo no) gamescope=$(gamescope_up && echo yes || echo no))."
exit 1
