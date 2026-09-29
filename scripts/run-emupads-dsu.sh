#!/usr/bin/env bash
# Launch emupads-dsu with the input group so Sunshine *(IMU) event nodes open.
# usermod -aG input does not update the user systemd manager credentials.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/scripts/emupads-dsu.py"
if command -v sg >/dev/null 2>&1 && grep -q "^input:.*\b${USER:-deck}\b" /etc/group 2>/dev/null; then
  exec sg input -c "/usr/bin/python3 $PY"
fi
exec /usr/bin/python3 "$PY"
