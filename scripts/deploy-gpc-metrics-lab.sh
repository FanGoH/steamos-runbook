#!/usr/bin/env bash
# Copy the Pi RAM dashboard to lab and enable the system unit.
# Caddy + Headscale DNS are separate (add-homelab-service / extra_records).
# Never sudo systemctl --user.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/lab/gpc-metrics"
HOST="${GPC_METRICS_LAB_HOST:-lab}"
DEST="${GPC_METRICS_LAB_DEST:-/home/fan/Projects/gpc-metrics}"

if [ ! -f "$SRC/server.py" ] || [ ! -f "$SRC/index.html" ]; then
  echo "missing $SRC"
  exit 1
fi

python3 "$SRC/server.py" --self-test >/dev/null
ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" "mkdir -p '$DEST'"
rsync -a --delete --exclude '*.sqlite*' --exclude '__pycache__' \
  "$SRC/server.py" "$SRC/index.html" "$SRC/gpc-metrics.service" \
  "$HOST:$DEST/"
ssh -o BatchMode=yes "$HOST" "python3 '$DEST/server.py' --self-test"
ssh -o BatchMode=yes "$HOST" bash -s <<EOF
set -euo pipefail
sudo cp '$DEST/gpc-metrics.service' /etc/systemd/system/gpc-metrics.service
sudo systemctl daemon-reload
sudo systemctl enable gpc-metrics.service
sudo systemctl restart gpc-metrics.service
sleep 1
curl -sf --max-time 3 http://127.0.0.1:8020/healthz >/dev/null \
  || curl -sS --max-time 3 http://127.0.0.1:8020/healthz || true
systemctl is-active gpc-metrics.service
EOF
echo "lab gpc-metrics deployed. Caddy host ram.tailnet.fangoh.dev -> 127.0.0.1:8020"
