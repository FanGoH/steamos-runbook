#!/usr/bin/env bash
# Cemuhook/DSU motion from Sunshine Switch Pro IMU → 127.0.0.1:26760 (Eden).
# Companion to emupads-mux (buttons/sticks). Never sudo systemctl --user.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SERVICE="${EMUPADS_DSU_SERVICE:-emupads-dsu.service}"
UNIT_PATH="/home/$STEAMOS_USER/.config/systemd/user/$SERVICE"
DSU_PY="$ROOT/scripts/emupads-dsu.py"
RUN_SH="$ROOT/scripts/run-emupads-dsu.sh"
LOG="$ROOT/logs/emupads-dsu.log"

chmod +x "$DSU_PY" "$RUN_SH" || true

if ! python3 -c 'import evdev' 2>/dev/null; then
  echo "python-evdev is missing (needed for $SERVICE)."
  exit 2
fi

if ! python3 "$DSU_PY" --self-test >/dev/null; then
  echo "emupads-dsu self-test failed."
  exit 1
fi

python3 "$DSU_PY" --enable-eden || true

mkdir -p "/home/$STEAMOS_USER/.config/systemd/user" "$ROOT/logs"

desired_unit="$(cat <<EOS
[Unit]
Description=EmuPads DSU (Sunshine Switch IMU → cemuhook :26760)
Documentation=file://$ROOT/.cursor/skills/bind-controller/SKILL.md
After=emupads-mux.service default.target

[Service]
Type=simple
ExecStart=$RUN_SH
Restart=always
RestartSec=1
Environment=HOME=/home/$STEAMOS_USER
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u "$STEAMOS_USER")
Environment=EMUPADS_DSU_LOG=$LOG
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target
WantedBy=gamescope-session.target
EOS
)"

unit_changed=0
if [ ! -f "$UNIT_PATH" ] || [ "$(cat "$UNIT_PATH")" != "$desired_unit" ]; then
  printf '%s\n' "$desired_unit" >"$UNIT_PATH"
  systemctl --user daemon-reload
  unit_changed=1
  echo "Updated $SERVICE unit."
fi

if ! systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1; then
  systemctl --user enable "$SERVICE"
  echo "Enabled $SERVICE."
fi

if systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  systemctl --user restart "$SERVICE"
  echo "Restarted $SERVICE."
else
  systemctl --user start "$SERVICE"
  echo "Started $SERVICE."
fi

sleep 0.5
if ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  echo "$SERVICE failed to stay up:"
  systemctl --user status "$SERVICE" --no-pager -l | tail -20 || true
  tail -20 "$LOG" 2>/dev/null || true
  exit 1
fi

echo "$SERVICE active."
tail -8 "$LOG" 2>/dev/null || true

# Hint when no IMU is visible yet (Moonlight disconnected or ACL).
if ! grep -q 'imu +' "$LOG" 2>/dev/null; then
  echo "No Sunshine IMU node seen yet — reconnect Moonlight with motion sensors on."
  echo "If IMU exists but DSU cannot open it, reinstall udev (seat tag) or:"
  echo "  for n in /sys/class/input/input*; do"
  echo "    grep -q '(IMU)' \"\$n/name\" 2>/dev/null || continue"
  echo "    for ev in \"\$n\"/event*; do sudo setfacl -m u:deck:rw /dev/input/\$(basename \"\$ev\"); done"
  echo "  done && systemctl --user restart emupads-dsu.service"
fi
exit 0
