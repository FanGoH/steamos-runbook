#!/usr/bin/env bash
# Desktop Anki window. Stops anki-connect.service first (one collection lock),
# then brings the daemon back when the window exits.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

FLATPAK_ID="${ANKI_FLATPAK_ID:-net.ankiweb.Anki}"
SERVICE="${ANKI_CONNECT_SERVICE:-anki-connect.service}"

restart_daemon() {
  systemctl --user start "$SERVICE" >/dev/null 2>&1 || true
}
trap restart_daemon EXIT

systemctl --user stop "$SERVICE" >/dev/null 2>&1 || true
# Drop the collection lock before the GUI opens.
for _ in 1 2 3 4 5; do
  pgrep -x anki >/dev/null 2>&1 || break
  sleep 0.2
done

# Do not exec: EXIT trap must restart the daemon after the window closes.
/usr/bin/flatpak run --user "$FLATPAK_ID" "$@"
