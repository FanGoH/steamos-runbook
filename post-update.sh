#!/usr/bin/env bash
# Restore host and user services after a SteamOS update.
# Safe to run multiple times; prefers checks before writes.
# Prints failures/warnings and manual actions together at the end.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/post-update-$(date +%Y%m%d-%H%M%S).log"
MANUAL_ACTIONS_FILE="$LOG_DIR/manual-actions-post-update.txt"
RESULTS_FILE="$LOG_DIR/post-update-results.txt"
export MANUAL_ACTIONS_FILE

mkdir -p "$LOG_DIR"
: >"$MANUAL_ACTIONS_FILE"
: >"$RESULTS_FILE"

if [ -t 1 ] && [ "${NO_COLOR:-}" = "" ]; then
  C_GREEN=$'\033[32m'
  C_YELLOW=$'\033[33m'
  C_RED=$'\033[31m'
  C_BOLD=$'\033[1m'
  C_RESET=$'\033[0m'
else
  C_GREEN=""; C_YELLOW=""; C_RED=""; C_BOLD=""; C_RESET=""
fi

echo "${C_BOLD}== SteamOS post-update recovery ==${C_RESET}"
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
  local rc

  echo "---- $name ----" | tee -a "$LOG_FILE"
  bash "$script" 2>&1 | tee -a "$LOG_FILE"
  rc=${PIPESTATUS[0]}

  if [ "$rc" -eq 0 ]; then
    echo "${C_GREEN}✅ OK${C_RESET}: $name" | tee -a "$LOG_FILE"
    echo "OK|$name|$rc" >>"$RESULTS_FILE"
  elif [ "$mode" = "warn" ] || [ "$rc" -eq 2 ]; then
    echo "${C_YELLOW}⚠️  WARN${C_RESET}: $name (exit $rc)" | tee -a "$LOG_FILE"
    echo "WARN|$name|$rc" >>"$RESULTS_FILE"
    warned=1
  else
    echo "${C_RED}❌ FAIL${C_RESET}: $name (exit $rc)" | tee -a "$LOG_FILE"
    echo "FAIL|$name|$rc" >>"$RESULTS_FILE"
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
run_step "check-decky" "$ROOT/scripts/check-decky.sh" warn
run_step "check-tailscale" "$ROOT/scripts/check-tailscale.sh" warn

echo "${C_BOLD}== verification checklist (health-check) ==${C_RESET}" | tee -a "$LOG_FILE"
echo | tee -a "$LOG_FILE"
SKIP_MANUAL_SUMMARY=1 bash "$ROOT/health-check.sh" 2>&1 | tee -a "$LOG_FILE"
health_rc=${PIPESTATUS[0]}
echo | tee -a "$LOG_FILE"

echo "${C_BOLD}== post-update summary ==${C_RESET}" | tee -a "$LOG_FILE"
echo | tee -a "$LOG_FILE"

echo "Results:" | tee -a "$LOG_FILE"
while IFS='|' read -r status name rc; do
  case "$status" in
    OK)   echo "  ${C_GREEN}✅${C_RESET} $name" | tee -a "$LOG_FILE" ;;
    WARN) echo "  ${C_YELLOW}⚠️${C_RESET}  $name (exit $rc)" | tee -a "$LOG_FILE" ;;
    FAIL) echo "  ${C_RED}❌${C_RESET} $name (exit $rc)" | tee -a "$LOG_FILE" ;;
  esac
done <"$RESULTS_FILE"
if [ "$health_rc" -eq 0 ]; then
  echo "  ${C_GREEN}✅${C_RESET} health-check" | tee -a "$LOG_FILE"
else
  echo "  ${C_RED}❌${C_RESET} health-check (exit $health_rc)" | tee -a "$LOG_FILE"
fi
echo | tee -a "$LOG_FILE"

if grep -q '^FAIL|' "$RESULTS_FILE" || [ "$health_rc" -ne 0 ]; then
  echo "${C_RED}${C_BOLD}Failures:${C_RESET}" | tee -a "$LOG_FILE"
  while IFS='|' read -r status name rc; do
    [ "$status" = "FAIL" ] || continue
    echo "  ❌ $name (exit $rc) — see \"---- $name ----\" in: $LOG_FILE" | tee -a "$LOG_FILE"
  done <"$RESULTS_FILE"
  if [ "$health_rc" -ne 0 ]; then
    echo "  ❌ health-check (exit $health_rc)" | tee -a "$LOG_FILE"
  fi
  echo | tee -a "$LOG_FILE"
fi

if grep -q '^WARN|' "$RESULTS_FILE"; then
  echo "${C_YELLOW}${C_BOLD}Warnings:${C_RESET}" | tee -a "$LOG_FILE"
  while IFS='|' read -r status name rc; do
    [ "$status" = "WARN" ] || continue
    echo "  ⚠️  $name (exit $rc)" | tee -a "$LOG_FILE"
  done <"$RESULTS_FILE"
  echo | tee -a "$LOG_FILE"
fi

print_manual_summary "$MANUAL_ACTIONS_FILE" | tee -a "$LOG_FILE"
echo | tee -a "$LOG_FILE"

if [ "$failed" -eq 0 ] && [ "$health_rc" -eq 0 ]; then
  echo "${C_GREEN}Automated recovery + health check finished OK.${C_RESET}" | tee -a "$LOG_FILE"
elif [ "$failed" -eq 0 ]; then
  echo "${C_YELLOW}Recovery steps OK, but health-check reported issues.${C_RESET}" | tee -a "$LOG_FILE"
else
  echo "${C_RED}Some recovery steps failed.${C_RESET} See Failures above; full output in $LOG_FILE" | tee -a "$LOG_FILE"
fi

if [ "$failed" -ne 0 ]; then
  exit "$failed"
fi
exit "$health_rc"
