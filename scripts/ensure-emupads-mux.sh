#!/usr/bin/env bash
# Always-on EmuPads P1/P2 uinput mux. Emulators bind the sinks; Decky only
# changes routing. Independent of dual-screen / sunshine-ds — vanilla
# Sunshine pads are sources too. Never sudo systemctl --user.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SERVICE="${EMUPADS_MUX_SERVICE:-emupads-mux.service}"
UNIT_PATH="/home/$STEAMOS_USER/.config/systemd/user/$SERVICE"
MUX_PY="$ROOT/scripts/emupads-mux.py"
BIND_PY="$ROOT/scripts/bind-gamepad.py"
LOG="$ROOT/logs/emupads-mux.log"
CONFIG="/home/$STEAMOS_USER/.config/emupads/mux.json"

if ! python3 -c 'import evdev' 2>/dev/null; then
  echo "python-evdev is missing (needed for $SERVICE)."
  record_manual "Install python-evdev for EmuPads mux" <<EOF
# SteamOS root is small; prefer a user install if pacman is blocked:
python3 -m pip install --user evdev
# Then:
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
$ROOT/scripts/ensure-emupads-mux.sh
EOF
  exit 2
fi

if ! python3 "$MUX_PY" --self-test >/dev/null; then
  echo "emupads-mux self-test failed."
  exit 1
fi

mkdir -p "/home/$STEAMOS_USER/.config/systemd/user" \
  "/home/$STEAMOS_USER/.config/emupads" \
  "$ROOT/logs"

if [ ! -f "$CONFIG" ]; then
  printf '%s\n' '{"mode": "shared", "sources": []}' >"$CONFIG"
  echo "Wrote default $CONFIG (shared P1, every host pad)."
fi

desired_unit="$(cat <<EOS
[Unit]
Description=EmuPads P1/P2 uinput mux
Documentation=file://$ROOT/.cursor/skills/bind-controller/SKILL.md
After=default.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $MUX_PY
Restart=always
RestartSec=1
Environment=HOME=/home/$STEAMOS_USER
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u "$STEAMOS_USER")
Environment=EMUPADS_MUX_CONFIG=$CONFIG
Environment=EMUPADS_MUX_LOG=$LOG
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

if [ "$unit_changed" -eq 1 ]; then
  systemctl --user restart "$SERVICE" || systemctl --user start "$SERVICE"
elif ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  systemctl --user start "$SERVICE"
fi

i=0
while [ "$i" -lt 25 ]; do
  if grep -qxs "EmuPads P1" /sys/class/input/js*/device/name 2>/dev/null; then
    echo "$SERVICE active; EmuPads P1 is up."
    python3 "$BIND_PY" apply --emu all --force >/dev/null || true
    echo "Bound Cemu / Azahar / Eden to EmuPads sinks (routing unchanged if mux.json exists)."
    exit 0
  fi
  sleep 0.2
  i=$((i + 1))
done

echo "EmuPads P1 did not appear after starting $SERVICE."
record_manual "Start EmuPads mux" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user status $SERVICE --no-pager
journalctl --user -u $SERVICE -n 40 --no-pager
tail -40 $LOG
EOF
exit 2
