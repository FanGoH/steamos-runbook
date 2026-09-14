#!/usr/bin/env bash
# Exit 0 when Tender Cemu/Azahar tiles should launch dual-screen.
#
# Default Auto: :48200 BUSY + gamescope-virtual sidecar, and Moonlight is
# actually watching the host second display (video/1 or GamePad-only).
# HDMI-only Moonlight (top screen) stays RetroDECK -f.
#
# Emu Pads toggle (~/.config/emupads/mux.json dual_screen):
#   auto — that check (default)
#   on   — BUSY + sidecar even if the client is top-only
#   off  — never dual-screen
#
# Ignore :47989 / :48100. Do not hardcode uniqueid.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# JSON reason on stderr so Tender/rom-launcher only see the exit code.
exec python3 "$ROOT/scripts/bind-gamepad.py" second-screen-streaming >&2
