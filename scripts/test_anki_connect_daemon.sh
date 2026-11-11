#!/usr/bin/env bash
# Offline checks for the headless AnkiConnect unit (no Flatpak start).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

DAEMON="$ROOT/scripts/anki-connect-daemon.sh"
GUI="$ROOT/scripts/anki-gui.sh"
ENSURE="$ROOT/scripts/ensure-anki.sh"

[ -x "$DAEMON" ] || fail "anki-connect-daemon.sh not executable"
[ -x "$GUI" ] || fail "anki-gui.sh not executable"
grep -q 'QT_QPA_PLATFORM=offscreen' "$DAEMON" || fail "daemon must use Qt offscreen"
grep -q 'unset DISPLAY WAYLAND_DISPLAY' "$DAEMON" || fail "daemon must drop gamescope DISPLAY"
if grep -qE '^[^#]*--safemode' "$DAEMON"; then
  fail "daemon must not pass --safemode"
fi
grep -q 'anki-connect.service' "$GUI" || fail "anki-gui.sh must stop anki-connect.service"
grep -q 'ANKICONNECT_PORT' "$ENSURE" || fail "ensure-anki.sh must pin AnkiConnect port"
grep -q 'WantedBy=gamescope-session.target' "$ENSURE" || fail "unit must start in Game Mode"

echo "test_anki_connect_daemon ok"
