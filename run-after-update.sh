#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$ROOT/scripts"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/after-update-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "$LOG_DIR"

echo "== SteamOS after-update runner =="
echo "Log: $LOG_FILE"
echo

failed=0

for script in "$SCRIPT_DIR"/*.sh; do
  [ -e "$script" ] || continue

  name="$(basename "$script")"
  echo "---- $name ----" | tee -a "$LOG_FILE"

  if bash "$script" 2>&1 | tee -a "$LOG_FILE"; then
    echo "OK: $name" | tee -a "$LOG_FILE"
  else
    echo "FAILED: $name" | tee -a "$LOG_FILE"
    failed=1
  fi

  echo | tee -a "$LOG_FILE"
done

exit "$failed"
