#!/usr/bin/env bash
# Ensure a systemd user service runs `agent worker start` for My Machines.
# SteamOS updates can disable user services; login is never automated.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SERVICE="$CURSOR_WORKER_SERVICE"
UNIT_PATH="/home/$STEAMOS_USER/.config/systemd/user/$SERVICE"
HEALTHZ="$(cursor_worker_healthz_url)"
WAIT_SECS="${CURSOR_WORKER_WAIT_SECS:-30}"
RUNNER="$ROOT/scripts/run-cursor-agent-worker.sh"

worker_healthz_up() {
  if command -v curl >/dev/null 2>&1; then
    curl -sf --max-time 2 "$HEALTHZ" >/dev/null 2>&1 && return 0
  fi
  return 1
}

worker_auth_required() {
  tail -n 40 "$ROOT/logs/cursor-agent-worker.log" 2>/dev/null | grep -q "Authentication required"
}

if [ ! -x "$RUNNER" ]; then
  chmod +x "$RUNNER"
fi

AGENT="$(cursor_agent_bin || true)"
if [ -z "$AGENT" ] || [ ! -x "$AGENT" ]; then
  echo "Cursor agent CLI not found."
  record_manual "Install Cursor agent CLI (user-local)" <<'EOF'
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"
agent status
# Then:
export XDG_RUNTIME_DIR=/run/user/$(id -u)
./scripts/ensure-cursor-agent.sh
EOF
  exit 2
fi
echo "Cursor agent CLI: $AGENT ($("$AGENT" --version 2>/dev/null || echo unknown))"

if [ ! -d "$CURSOR_WORKER_DIR" ]; then
  echo "Worker dir missing: $CURSOR_WORKER_DIR"
  record_manual "Create or set CURSOR_WORKER_DIR" <<EOF
mkdir -p $CURSOR_WORKER_DIR
# Or set CURSOR_WORKER_DIR in .env to an existing checkout.
EOF
  exit 2
fi

echo "Worker data dir: $CURSOR_WORKER_DATA_DIR"
echo "Worker roots:"
mapfile -t worker_dirs < <(cursor_worker_dirs) || true
if [ "${#worker_dirs[@]}" -eq 0 ]; then
  echo "  (none)"
  record_manual "Set CURSOR_WORKER_DIR to a real directory" <<EOF
# Current: $CURSOR_WORKER_DIR
EOF
  exit 2
fi
for d in "${worker_dirs[@]}"; do
  echo "  - $d"
done

logged_in=1
if ! "$AGENT" status >/dev/null 2>&1; then
  logged_in=0
  echo "Cursor agent is not logged in."
  record_manual "Login to Cursor agent (do not put API keys in the repo)" <<EOF
export PATH="\$HOME/.local/bin:\$PATH"
agent login
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user restart $SERVICE
EOF
fi

mkdir -p "/home/$STEAMOS_USER/.config/systemd/user" "$ROOT/logs" "$CURSOR_WORKER_DATA_DIR"

# Encode workspace roots in the unit so .env extra-dir changes restart
# a healthy worker. Do not restart just because the runner file is newer.
worker_roots_comment="# WorkerRoots: ${worker_dirs[*]}"
desired_unit="$(cat <<EOS
[Unit]
Description=Cursor Agent worker (My Machines)
Documentation=file://$ROOT/README.md
After=default.target
# Must not PartOf=/BindsTo= the Cursor AppImage — this worker outlives the GUI.
StartLimitIntervalSec=120
StartLimitBurst=8
$worker_roots_comment

[Service]
Type=simple
ExecStart=$RUNNER
Restart=always
RestartSec=10
RestartPreventExitStatus=75
Environment=HOME=/home/$STEAMOS_USER
Environment=PATH=/home/$STEAMOS_USER/.local/bin:/usr/bin:/bin
StandardOutput=append:$ROOT/logs/cursor-agent-worker.log
StandardError=append:$ROOT/logs/cursor-agent-worker.log

[Install]
WantedBy=default.target
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
else
  echo "$SERVICE already enabled."
fi

if worker_healthz_up && [ "$unit_changed" -eq 0 ]; then
  echo "$SERVICE already healthy ($HEALTHZ)."
  exit 0
fi

systemctl --user reset-failed "$SERVICE" >/dev/null 2>&1 || true

if [ "$logged_in" -eq 0 ]; then
  systemctl --user stop "$SERVICE" >/dev/null 2>&1 || true
  echo "Unit installed; worker will stay down until agent login succeeds."
  exit 2
fi

if [ "$unit_changed" -eq 1 ] || ! worker_healthz_up; then
  if systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
    systemctl --user restart "$SERVICE" || true
    echo "Restarted $SERVICE after unit change or dead healthz."
  else
    systemctl --user start "$SERVICE" || true
    echo "Started $SERVICE."
  fi
fi

echo "Waiting up to ${WAIT_SECS}s for worker healthz at $HEALTHZ..."
waited=0
while [ "$waited" -lt "$WAIT_SECS" ]; do
  if worker_healthz_up; then
    echo "$SERVICE is healthy ($HEALTHZ)."
    exit 0
  fi
  if worker_auth_required && ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  waited=$((waited + 1))
done

if worker_auth_required; then
  systemctl --user stop "$SERVICE" >/dev/null 2>&1 || true
  echo "Worker needs agent login (status can still look logged in)."
  record_manual "Login to Cursor agent (do not put API keys in the repo)" <<EOF
export PATH="\$HOME/.local/bin:\$PATH"
agent login
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user reset-failed $SERVICE
systemctl --user restart $SERVICE
EOF
  exit 2
fi

if systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
  echo "Warning: $SERVICE is active but healthz is not answering yet."
  record_manual "Check Cursor agent worker logs" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user status $SERVICE --no-pager
tail -n 50 $ROOT/logs/cursor-agent-worker.log
agent worker debug
EOF
  exit 2
fi

echo "Warning: $SERVICE is not active."
record_manual "Start Cursor agent worker (no sudo)" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
# If login expired:
agent login
systemctl --user reset-failed $SERVICE
systemctl --user enable --now $SERVICE
systemctl --user status $SERVICE --no-pager
tail -n 50 $ROOT/logs/cursor-agent-worker.log
EOF
exit 1
