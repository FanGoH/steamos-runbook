#!/usr/bin/env bash
# Start the Steam overlay / qAM emulator-input inhibitor if it is not up.
# Safe to call from rom-launcher, Game Mode dual-screen, and Eden wrap.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
LOG="${EMU_STEAM_UI_INHIBIT_LOG:-$ROOT/logs/emu-steam-ui-inhibit.log}"
mkdir -p "$(dirname "$LOG")"
nohup python3 "$ROOT/scripts/inhibit-emu-input-on-steam-ui.py" --ensure >>"$LOG" 2>&1 &
disown $! 2>/dev/null || true
