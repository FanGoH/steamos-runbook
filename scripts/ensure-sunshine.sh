#!/usr/bin/env bash
# Decky Sunshine is the only starter. Do not enable the Flatpak user unit.
#
# SteamOS Game Mode needs Decky's setuid bwrap for KMS. A second systemd
# Flatpak instance races it, truncates the shared sunshine.log, and leaves
# GameStream SUNSHINE_SERVER_BUSY after Game Mode → Desktop switches.
# Do not delete the Flatpak app or its config — Decky launches that same
# install (dev.lizardbyte.app.Sunshine).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

WAIT_SECS="${SUNSHINE_WAIT_SECS:-25}"
UNIT_PATH="/home/$STEAMOS_USER/.config/systemd/user/$SUNSHINE_USER_SERVICE"

manual_start_decky() {
  record_manual "Start Sunshine from Decky Sunshine (do not enable systemd)" <<EOF
# In Game Mode or Desktop: Decky → Sunshine → Start
# Or wait for PluginLoader; lastRunState is already 'start'.
# Do not run: systemctl --user enable --now $SUNSHINE_USER_SERVICE
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
EOF
}

disable_systemd_autostart() {
  local changed=0
  if sunshine_systemd_enabled || sunshine_systemd_active; then
    echo "Disabling redundant $SUNSHINE_USER_SERVICE (Decky Sunshine is the starter)."
    systemctl --user disable --now "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1 || true
    systemctl --user stop "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1 || true
    changed=1
  fi
  # Drop leftover user-instance Flatpak if systemd already stopped but bwrap remains.
  if pgrep -u "$STEAMOS_USER" -x sunshine >/dev/null 2>&1 && sunshine_systemd_active; then
    systemctl --user stop "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1 || true
    changed=1
  fi
  if [ -f "$UNIT_PATH" ] && grep -q '^WantedBy=' "$UNIT_PATH"; then
    echo "User unit $UNIT_PATH remains on disk (disabled); Flatpak config is kept."
  fi
  if [ "$changed" -eq 1 ]; then
    echo "Systemd Sunshine autostart is off."
  else
    echo "Systemd Sunshine autostart already off."
  fi
}

wait_for_state() {
  local want="$1"
  local waited=0
  local state
  while [ "$waited" -lt "$WAIT_SECS" ]; do
    state="$(sunshine_serverinfo_state 2>/dev/null || true)"
    if [ "$state" = "$want" ]; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

disable_systemd_autostart

# A second user-owned sunshine (Flatpak/systemd) next to Decky's root instance.
user_sunshine="$(pgrep -u "$STEAMOS_USER" -x sunshine 2>/dev/null || true)"
if [ -n "$user_sunshine" ]; then
  echo "Stopping leftover user Sunshine PID(s): $user_sunshine"
  # Prefer systemd stop (ExecStop=flatpak kill). Do not kill Decky's root instance.
  systemctl --user stop "$SUNSHINE_USER_SERVICE" >/dev/null 2>&1 || true
  if command -v flatpak >/dev/null 2>&1; then
    # Only the user Flatpak instance shows up in `flatpak ps` here.
    flatpak kill "$SUNSHINE_FLATPAK_ID" >/dev/null 2>&1 || true
  fi
  sleep 1
fi

state="$(sunshine_serverinfo_state 2>/dev/null || true)"
echo "GameStream state: ${state:-DOWN} currentgame=$(sunshine_currentgame || echo none)"

if [ -z "$state" ] || [ "$state" = "DOWN" ] || [ "$state" = "UNKNOWN" ]; then
  echo "Sunshine GameStream is not answering on ${SUNSHINE_GAMESTREAM_URL}."
  echo "Decky Sunshine should start the Flatpak (privileged bwrap in Game Mode)."
  manual_start_decky
  exit 2
fi

if [ "$state" = "FREE" ]; then
  echo "Sunshine is FREE (Decky-owned). Systemd autostart is disabled."
  exit 0
fi

if sunshine_stream_udp_up; then
  echo "Sunshine is BUSY with live stream UDP — leaving the session alone."
  exit 0
fi

echo "Sunshine is BUSY (currentgame=$(sunshine_currentgame)) with no stream UDP — stale session."
echo "Restarting the Decky-owned instance via the local HTTPS API."
if sunshine_restart_via_api; then
  echo "Issued /api/restart."
else
  echo "Could not call /api/restart (missing Decky auth header?)."
  record_manual "Restart Sunshine from Decky to clear BUSY/503" <<EOF
# Decky → Sunshine → Stop, then Start
# Do not enable $SUNSHINE_USER_SERVICE
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
EOF
  exit 2
fi

if wait_for_state FREE; then
  echo "Sunshine is FREE after restart."
  exit 0
fi

echo "Warning: GameStream did not return FREE after restart."
record_manual "Confirm Sunshine from Decky after stale-session restart" <<EOF
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
# Expect SUNSHINE_SERVER_FREE and currentgame 0
# If still down: Decky → Sunshine → Start
EOF
exit 2
