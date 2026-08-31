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
WATCH_SERVICE="${SUNSHINE_WATCH_SERVICE:-steamos-sunshine-watch.service}"
WATCH_TIMER="${SUNSHINE_WATCH_TIMER:-steamos-sunshine-watch.timer}"
WATCH_PATH="${SUNSHINE_WATCH_PATH:-steamos-sunshine-watch.path}"
WATCH_DIR="/home/$STEAMOS_USER/.config/systemd/user"
WATCH_SCRIPT="$ROOT/scripts/sunshine-watch.sh"
WATCH_LOG="$ROOT/logs/sunshine-watch.log"

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

# FREE or BUSY — GameStream is answering. startSunshine can return true
# after a failed bwrap while :47989 is still down.
wait_for_gamestream() {
  local waited=0
  local state
  while [ "$waited" -lt "$WAIT_SECS" ]; do
    state="$(sunshine_serverinfo_state 2>/dev/null || true)"
    if [ "$state" = "FREE" ] || [ "$state" = "BUSY" ]; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

# Playbook session hook — not the Flatpak Sunshine unit and not a poll loop.
# chmod 755 on the Pulse dir so Decky's setuid bwrap can bind-mount the socket,
# then start Sunshine via Decky if GameStream is still down. Path unit fires
# when pulse/native appears; the service also runs at default.target.
install_watch_units() {
  mkdir -p "$WATCH_DIR" "$ROOT/logs"
  chmod +x "$WATCH_SCRIPT" 2>/dev/null || true

  if systemctl --user is-enabled "$WATCH_TIMER" >/dev/null 2>&1 \
    || systemctl --user is-active "$WATCH_TIMER" >/dev/null 2>&1; then
    systemctl --user disable --now "$WATCH_TIMER" >/dev/null 2>&1 || true
    echo "Disabled polling $WATCH_TIMER (Pulse dir chmod replaces monitor→act)."
  fi
  rm -f "$WATCH_DIR/$WATCH_TIMER"

  local desired_service desired_path
  desired_service="$(cat <<EOS
[Unit]
Description=SteamOS playbook Sunshine Pulse-ready start
After=default.target pipewire-pulse.service pipewire-pulse.socket

[Service]
Type=oneshot
Nice=10
TimeoutStartSec=120
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStart=$WATCH_SCRIPT
StandardOutput=append:$WATCH_LOG
StandardError=append:$WATCH_LOG

[Install]
WantedBy=default.target
EOS
)"
  desired_path="$(cat <<EOS
[Unit]
Description=SteamOS playbook Sunshine when Pulse appears

[Path]
PathExists=/run/user/%U/pulse/native
Unit=$WATCH_SERVICE
MakeDirectory=false

[Install]
WantedBy=default.target
EOS
)"

  local service_path="$WATCH_DIR/$WATCH_SERVICE"
  local path_unit="$WATCH_DIR/$WATCH_PATH"
  local changed=0
  if [ ! -f "$service_path" ] || [ "$(cat "$service_path")" != "$desired_service" ]; then
    printf '%s\n' "$desired_service" >"$service_path"
    changed=1
  fi
  if [ ! -f "$path_unit" ] || [ "$(cat "$path_unit")" != "$desired_path" ]; then
    printf '%s\n' "$desired_path" >"$path_unit"
    changed=1
  fi
  if [ "$changed" -eq 1 ]; then
    systemctl --user daemon-reload
    echo "Updated $WATCH_SERVICE and $WATCH_PATH (Pulse-ready start, no poll)."
  fi
  if ! systemctl --user is-enabled "$WATCH_SERVICE" >/dev/null 2>&1; then
    systemctl --user enable "$WATCH_SERVICE"
    echo "Enabled $WATCH_SERVICE at default.target."
  fi
  if ! systemctl --user is-enabled "$WATCH_PATH" >/dev/null 2>&1; then
    systemctl --user enable --now "$WATCH_PATH"
    echo "Enabled $WATCH_PATH."
  elif [ "$changed" -eq 1 ]; then
    systemctl --user restart "$WATCH_PATH"
    echo "Restarted $WATCH_PATH after unit change."
  else
    echo "$WATCH_PATH already enabled."
  fi
}

disable_systemd_autostart
install_watch_units
sunshine_open_pulse_dir >/dev/null 2>&1 || true

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
  last_run="$(sunshine_decky_last_run_state 2>/dev/null || echo missing)"
  echo "Decky lastRunState: ${last_run}"
  if [ "$last_run" = "stop" ]; then
    echo "Decky lastRunState is stop — not auto-starting."
    manual_start_decky
    exit 2
  fi
  echo "Waiting for Pulse (${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse/native) before asking Decky to start."
  if sunshine_wait_for_pulse; then
    if sunshine_open_pulse_dir; then
      echo "Pulse is up and bind-mountable (dir mode 755)."
    else
      echo "Pulse socket exists but chmod 755 on the pulse dir failed."
    fi
  else
    echo "Pulse socket not ready yet; still asking Decky to start."
  fi
  echo "Calling Decky Sunshine startSunshine via PluginLoader (not systemd, not /api/restart)."
  if sunshine_start_via_decky; then
    echo "Decky accepted startSunshine."
  else
    echo "Could not ask Decky to start Sunshine."
    manual_start_decky
    exit 2
  fi
  # startSunshine can return true on a flatpak-ps false positive; wait for GameStream.
  if wait_for_gamestream; then
    state="$(sunshine_serverinfo_state 2>/dev/null || true)"
    echo "GameStream state after Decky start: ${state:-DOWN} currentgame=$(sunshine_currentgame || echo none)"
  else
    echo "GameStream still down after Decky startSunshine (boot Pulse race?)."
    manual_start_decky
    exit 2
  fi
fi

if [ "$state" = "FREE" ]; then
  echo "Sunshine is FREE (Decky-owned). Systemd autostart is disabled."
  login_state="$(sunshine_ui_login_state 2>/dev/null || true)"
  echo "Web UI login: ${login_state}"
  if [ "$login_state" = "UNAUTH_HASH_OK" ]; then
    echo "UI 401 with a hash-matching password (zombie host). Closing leftover app."
    if sunshine_close_app_via_api && wait_for_state FREE; then
      echo "Sunshine is FREE after closing leftover app."
      exit 0
    fi
    record_manual "Close leftover Sunshine app — Web UI 401 with valid stored password" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
# Decky → Sunshine → Stop, then Start
# Do not POST /api/restart (kills Decky's setuid Sunshine)
curl -sk -o /dev/null -w '%{http_code}\n' $SUNSHINE_UI_URL/api/apps
EOF
    exit 2
  fi
  exit 0
fi

if sunshine_stream_udp_up; then
  echo "Sunshine is BUSY with live stream UDP — leaving the session alone."
  exit 0
fi

echo "Sunshine is BUSY (currentgame=$(sunshine_currentgame)) with no stream UDP — stale session."
echo "Closing leftover app via POST /api/apps/close (do not /api/restart the Decky instance)."
if sunshine_close_app_via_api; then
  echo "Issued /api/apps/close."
else
  echo "Could not call /api/apps/close (missing Decky auth header?)."
  record_manual "Close leftover Sunshine app from Decky" <<EOF
# Decky → Sunshine → Stop the running app / Stop, then Start
# Do not: curl .../api/restart  (kills Decky's setuid Sunshine)
# Do not enable $SUNSHINE_USER_SERVICE
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
EOF
  exit 2
fi

if wait_for_state FREE; then
  echo "Sunshine is FREE after closing leftover Desktop/app."
  exit 0
fi

echo "Warning: GameStream did not return FREE after /api/apps/close."
record_manual "Confirm Sunshine from Decky after closing leftover app" <<EOF
curl -s $SUNSHINE_GAMESTREAM_URL/serverinfo
# Expect SUNSHINE_SERVER_FREE and currentgame 0
# If still down: Decky → Sunshine → Start
EOF
exit 2
