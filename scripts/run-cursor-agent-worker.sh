#!/usr/bin/env bash
# Long-lived Cursor My Machines worker. Invoked by cursor-agent-worker.service.
# Worker flags must come before `start`. Idle timeout 0 keeps the process up
# so systemd is not racing a clean hourly idle-exit.
# Uses CURSOR_WORKER_DATA_DIR so this does not fight the on-demand session
# worker lock in ~/.local/share/cursor-agent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

export PATH="${HOME:-/home/${STEAMOS_USER}}/.local/bin:/usr/bin:/bin${PATH:+:$PATH}"

AGENT="$(cursor_agent_bin)" || {
  echo "Cursor agent CLI not found (expected $CURSOR_AGENT_BIN)." >&2
  exit 1
}

mapfile -t worker_dirs < <(cursor_worker_dirs) || true
if [ "${#worker_dirs[@]}" -eq 0 ]; then
  echo "No worker dirs (CURSOR_WORKER_DIR=$CURSOR_WORKER_DIR)." >&2
  exit 1
fi

# User lingering starts this before DNS is up; wait rather than crash-loop.
waited=0
wait_secs="${CURSOR_WORKER_NET_WAIT_SECS:-60}"
until getent hosts api2.cursor.sh >/dev/null 2>&1; do
  if [ "$waited" -ge "$wait_secs" ]; then
    echo "api2.cursor.sh still unresolvable after ${wait_secs}s." >&2
    break
  fi
  sleep 2
  waited=$((waited + 2))
done

args=(worker)
# First --worker-dir is the My Machines assignment identity (must be this
# playbook so reboot still serves steamos-runbook). Extra dirs are additional
# workspace roots on the same worker, not extra repo registrations.
for d in "${worker_dirs[@]}"; do
  args+=(--worker-dir "$d")
done
mkdir -p "$CURSOR_WORKER_DATA_DIR"
args+=(--management-addr "$CURSOR_WORKER_MGMT_ADDR")
args+=(--idle-release-timeout "$CURSOR_WORKER_IDLE_RELEASE_TIMEOUT")
args+=(--data-dir "$CURSOR_WORKER_DATA_DIR")
if [ -n "${CURSOR_WORKER_NAME:-}" ]; then
  args+=(--name "$CURSOR_WORKER_NAME")
fi
args+=(start)

exec "$AGENT" "${args[@]}"
