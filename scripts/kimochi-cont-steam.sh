#!/bin/sh
# Kimochi's gamescope-input watchdog SIGSTOPs steam. Resume it so Guide/QAM
# work after the overlay exits (or dies mid-pause).
set -eu
PATH="/usr/bin:/bin:${PATH:-}"
export PATH
for pid in $(ps -eo pid,comm | awk '$2=="kimochi-input"{print $1}'); do
  kill -TERM "$pid" 2>/dev/null || true
done
for pid in $(ps -eo pid,stat,comm | awk '$3=="steam" && $2 ~ /T/{print $1}'); do
  echo "Kimochi overlay: SIGCONT steam pid $pid" >&2
  kill -CONT "$pid" 2>/dev/null || true
done
exit 0
