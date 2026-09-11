#!/usr/bin/env bash
# Start the Steam overlay / QAM / Home mute watcher if it is not up.
# Safe to call from rom-launcher, Game Mode dual-screen, and Eden wrap.
# Hop out of Steam's tile cgroup: nohup/disown stay in app-steam-app*.scope
# and the reaper's waitpid leaves Steam on "Exiting…".
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
LOG="${EMU_STEAM_UI_INHIBIT_LOG:-$ROOT/logs/emu-steam-ui-inhibit.log}"
mkdir -p "$(dirname "$LOG")"

if [ -z "${EMU_STEAM_UI_INHIBIT_INNER:-}" ] && command -v systemd-run >/dev/null 2>&1; then
  systemctl --user reset-failed emu-steam-ui-inhibit-start.service 2>/dev/null || true
  if systemd-run --user --collect --quiet \
       --unit=emu-steam-ui-inhibit-start \
       --property=Type=oneshot \
       --property=KillMode=process \
       --setenv=EMU_STEAM_UI_INHIBIT_INNER=1 \
       --setenv=XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}" \
       --setenv=HOME="${HOME:-/home/deck}" \
       /bin/bash "$ROOT/scripts/start-emu-steam-ui-inhibit.sh"; then
    exit 0
  fi
fi

nohup python3 "$ROOT/scripts/inhibit-emu-input-on-steam-ui.py" --ensure >>"$LOG" 2>&1 &
disown $! 2>/dev/null || true
