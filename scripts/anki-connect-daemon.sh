#!/usr/bin/env bash
# Headless Anki so AnkiConnect stays up in Plasma and Game Mode.
# Qt offscreen: do not inherit gamescope DISPLAY (would put a window on the TV).
# Do not pass --safemode (that disables add-ons, including AnkiConnect).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

FLATPAK_ID="${ANKI_FLATPAK_ID:-net.ankiweb.Anki}"
PROFILE="${ANKI_PROFILE:-User 1}"

export QT_QPA_PLATFORM=offscreen
export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:---disable-gpu}"
unset DISPLAY WAYLAND_DISPLAY || true

exec /usr/bin/flatpak run --user \
  --env=QT_QPA_PLATFORM=offscreen \
  --env=QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS}" \
  "$FLATPAK_ID" \
  -p "$PROFILE"
