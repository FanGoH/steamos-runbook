#!/usr/bin/env bash
# Bring up NUXBT (NXBT fork) for Switch 2 remote-play experiments.
# Additive only — does not enable switch2-controllers / nso-gc.
# BlueZ override lives under /run (cleared on reboot); toggle off when done.
#
# Important: do NOT run `nuxbt toggle` inside Distrobox — it cannot restart
# host bluetooth. Use scripts/nuxbt-bluez-override.sh on the host instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

DIR="${NUXBT_DIR:-/home/${STEAMOS_USER}/code/nuxbt}"
CONTAINER="${NUXBT_DISTROBOX:-steamos-tools}"
VENV="$DIR/.venv"
NUXBT="$VENV/bin/nuxbt"
OVERRIDE="$ROOT/scripts/nuxbt-bluez-override.sh"

mkdir -p "$DIR"

if ! command -v distrobox >/dev/null 2>&1; then
  echo "distrobox missing"
  exit 1
fi

if ! distrobox list 2>/dev/null | grep -q "[[:space:]]${CONTAINER}[[:space:]]"; then
  echo "Distrobox container '$CONTAINER' not found (expected sunshine-ds steamos-tools)."
  exit 1
fi

echo "Ensuring NUXBT build deps in Distrobox '$CONTAINER'…"
distrobox enter "$CONTAINER" -- bash -lc '
set -e
sudo dnf install -y python3.12 python3-pip python3-devel gcc \
  cairo-devel cairo-gobject-devel gobject-introspection-devel \
  dbus-devel pkgconf-pkg-config bluez-libs-devel \
  python3-gobject python3-cairo >/dev/null
'

if [ ! -x "$NUXBT" ]; then
  echo "Creating venv and installing nuxbt into $DIR"
  distrobox enter "$CONTAINER" -- bash -lc "
set -e
cd '$DIR'
python3.12 -m venv .venv
.venv/bin/pip install -U pip wheel
.venv/bin/pip install nuxbt
"
fi

echo "NUXBT: $("$NUXBT" --version 2>/dev/null || true)"
"$OVERRIDE" status || true

if [ ! -f /run/systemd/system/bluetooth.service.d/nuxbt.conf ]; then
  record_manual "Enable NUXBT BlueZ override on the HOST (not Distrobox)" <<EOF
# Do not use: distrobox … nuxbt toggle  (fails: no host system bus)
# Optional: pause Switch2 pad→PC bridge for the test only
systemctl --user stop nso-gc.service 2>/dev/null || true

sudo $OVERRIDE enable
$OVERRIDE status

# On Switch 2: Controllers → Change Grip/Order, then:
distrobox enter $CONTAINER -- bash -lc 'export PATH=$VENV/bin:\$PATH; nuxbt demo'

# When finished:
sudo $OVERRIDE disable
systemctl --user start nso-gc.service 2>/dev/null || true
EOF
  echo "BlueZ override not enabled yet. Run on the host: sudo $OVERRIDE enable"
  exit 2
fi

record_manual "Pair NUXBT Pro Controller with Switch 2" <<EOF
# On Switch 2: Controllers → Change Grip/Order, then:
distrobox enter $CONTAINER -- bash -lc 'export PATH=$VENV/bin:\$PATH; nuxbt demo'
# When finished:
sudo $OVERRIDE disable
systemctl --user start nso-gc.service 2>/dev/null || true
EOF

echo "BlueZ override present. Open Switch 2 Change Grip/Order, then run nuxbt demo."
exit 0
