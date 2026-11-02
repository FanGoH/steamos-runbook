#!/usr/bin/env bash
# Always-on RAM / swap / PSI sampler. Writes daily jsonl under
# logs/resources/ and latest.html. Not a substitute for earlyoom
# (hourly journal one-liners). Never sudo systemctl --user.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SERVICE="${WATCH_RESOURCES_SERVICE:-steamos-watch-resources.service}"
UNIT_PATH="/home/$STEAMOS_USER/.config/systemd/user/$SERVICE"
WATCH_PY="$ROOT/scripts/watch-resources.py"
LOG="$ROOT/logs/resources/watch.log"
INTERVAL="${WATCH_RESOURCES_INTERVAL:-5}"
KEEP_DAYS="${WATCH_RESOURCES_KEEP_DAYS:-14}"

if [ ! -f "$WATCH_PY" ]; then
  echo "Missing $WATCH_PY"
  exit 1
fi

mkdir -p "/home/$STEAMOS_USER/.config/systemd/user" "$ROOT/logs/resources"

desired_unit="$(cat <<EOS
[Unit]
Description=Playbook RAM / swap / PSI sampler
After=default.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $WATCH_PY watch --rolling --interval $INTERVAL --keep-days $KEEP_DAYS
Restart=always
RestartSec=2
Environment=HOME=/home/$STEAMOS_USER
Environment=XDG_RUNTIME_DIR=/run/user/$(id -u "$STEAMOS_USER")
Environment=STEAMOS_PLAYBOOK_DIR=$ROOT
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
while [ "$i" -lt 15 ]; do
  if systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
    echo "$SERVICE active; samples → $ROOT/logs/resources/ (HTML: fgpc host ram report)."
    exit 0
  fi
  sleep 0.2
  i=$((i + 1))
done

echo "$SERVICE did not become active."
record_manual "Start RAM watcher" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user status $SERVICE --no-pager
journalctl --user -u $SERVICE -n 40 --no-pager
tail -40 $LOG
EOF
exit 2
