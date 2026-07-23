#!/usr/bin/env bash
# Restore host and user services after a SteamOS update.
# Safe to run multiple times; prefers checks before writes.
# Prints a summary of any manual commands still needed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/post-update-$(date +%Y%m%d-%H%M%S).log"
MANUAL_ACTIONS_FILE="$LOG_DIR/manual-actions-post-update.txt"
export MANUAL_ACTIONS_FILE

mkdir -p "$LOG_DIR"
: >"$MANUAL_ACTIONS_FILE"

echo "== SteamOS post-update recovery =="
echo "Log: $LOG_FILE"
echo
echo "SteamOS updates can remove udev rules, disable user services, and reset"
echo "pacman keyrings while keeping scripts in /home/deck."
echo "This script restores what it can automatically and prints exact manual"
echo "commands only for steps that need a human (e.g. Tailscale login)."
echo

failed=0
warned=0

run_step() {
  local name="$1"
  local script="$2"
  local mode="${3:-fail}" # fail | warn

  echo "---- $name ----" | tee -a "$LOG_FILE"
  bash "$script" 2>&1 | tee -a "$LOG_FILE"
  local rc=${PIPESTATUS[0]}

  if [ "$rc" -eq 0 ]; then
    echo "OK: $name" | tee -a "$LOG_FILE"
  elif [ "$mode" = "warn" ] || [ "$rc" -eq 2 ]; then
    echo "WARN: $name (exit $rc) — see manual actions if printed" | tee -a "$LOG_FILE"
    warned=1
  else
    echo "FAILED: $name (exit $rc)" | tee -a "$LOG_FILE"
    failed=1
  fi
  echo | tee -a "$LOG_FILE"
}

run_step "ensure-pacman" "$ROOT/scripts/ensure-pacman.sh"
run_step "ensure-sshd" "$ROOT/scripts/ensure-sshd.sh"
run_step "ensure-wol" "$ROOT/scripts/ensure-wol.sh"
run_step "ensure-openrgb" "$ROOT/scripts/ensure-openrgb.sh"
run_step "ensure-sunshine" "$ROOT/scripts/ensure-sunshine.sh"
run_step "ensure-gearlever" "$ROOT/scripts/ensure-gearlever.sh"
export DECKY_REMIND_REINSTALL=1
run_step "check-decky" "$ROOT/scripts/check-decky.sh" warn
unset DECKY_REMIND_REINSTALL
run_step "check-tailscale" "$ROOT/scripts/check-tailscale.sh" warn

echo "== post-update summary ==" | tee -a "$LOG_FILE"
print_manual_summary "$MANUAL_ACTIONS_FILE" | tee -a "$LOG_FILE"
echo | tee -a "$LOG_FILE"

if [ "$failed" -eq 0 ]; then
  echo "Automated recovery finished." | tee -a "$LOG_FILE"
  echo "Run ./health-check.sh to verify status." | tee -a "$LOG_FILE"
else
  echo "Some recovery steps failed; see log and manual actions above." | tee -a "$LOG_FILE"
fi

exit "$failed"
