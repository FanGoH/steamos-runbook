#!/usr/bin/env bash
# Initial setup for a fresh SteamOS gaming PC. Safe to re-run.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/bootstrap-$(date +%Y%m%d-%H%M%S).log"
MANUAL_ACTIONS_FILE="$LOG_DIR/manual-actions-bootstrap.txt"
export MANUAL_ACTIONS_FILE

mkdir -p "$LOG_DIR"
: >"$MANUAL_ACTIONS_FILE"

if [ ! -f "$ROOT/.env" ]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example; edit it if needed."
fi

echo "== SteamOS playbook bootstrap =="
echo "Log: $LOG_FILE"
echo

failed=0
warned=0

run_step() {
  local name="$1"
  local script="$2"
  local mode="${3:-fail}"

  echo "---- $name ----" | tee -a "$LOG_FILE"
  bash "$script" 2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}

  if [ "$rc" -eq 0 ]; then
    echo "OK: $name" | tee -a "$LOG_FILE"
  elif [ "$mode" = "warn" ] || [ "$rc" -eq 2 ]; then
    echo "WARN: $name (exit $rc) — see manual actions if printed" | tee -a "$LOG_FILE"
    warned=1
  else
    echo "FAILED: $name" | tee -a "$LOG_FILE"
    failed=1
  fi
  echo | tee -a "$LOG_FILE"
}

for script in "$ROOT/scripts"/[0-9]*.sh; do
  [ -e "$script" ] || continue
  run_step "$(basename "$script")" "$script"
done

run_step "ensure-pacman" "$ROOT/scripts/ensure-pacman.sh"
run_step "ensure-sshd" "$ROOT/scripts/ensure-sshd.sh"
run_step "ensure-wol" "$ROOT/scripts/ensure-wol.sh"
run_step "ensure-openrgb" "$ROOT/scripts/ensure-openrgb.sh"
run_step "ensure-sunshine" "$ROOT/scripts/ensure-sunshine.sh"
run_step "ensure-gearlever" "$ROOT/scripts/ensure-gearlever.sh"
run_step "check-decky" "$ROOT/scripts/check-decky.sh" warn
run_step "check-tailscale" "$ROOT/scripts/check-tailscale.sh" warn

echo "== bootstrap summary ==" | tee -a "$LOG_FILE"
print_manual_summary "$MANUAL_ACTIONS_FILE" | tee -a "$LOG_FILE"
echo | tee -a "$LOG_FILE"

if [ "$failed" -eq 0 ]; then
  echo "Bootstrap completed. Run ./health-check.sh to verify." | tee -a "$LOG_FILE"
else
  echo "Bootstrap finished with errors; see log and manual actions above." | tee -a "$LOG_FILE"
fi

exit "$failed"
