#!/usr/bin/env bash
# Download PS2 BIOS files through Tender's firmware backend (same as the
# Decky BIOS UI) and pin PCSX2.ini to USA v2.30. Registry marks every PS2
# BIOS required=false, so download_required_firmware is a no-op — use all.
# Do not raw-curl RomM; that 403s without Tender's token/User-Agent.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

TENDER_PY="$ROOT/scripts/tender-firmware.py"
BIOS_DIR="${RETRODECK_BIOS_DIR:-/home/${STEAMOS_USER}/retrodeck/bios}"
PCSX2_INI="${PCSX2_INI:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/config/PCSX2/inis/PCSX2.ini}"
LOADER="${DECKY_LOADER_URL:-http://127.0.0.1:1337}"
PLUGIN="${TENDER_PLUGIN_NAME:-Tender}"

if [ ! -f "$TENDER_PY" ]; then
  echo "Missing $TENDER_PY"
  exit 1
fi

if ! python3 "$TENDER_PY" --self-test; then
  echo "Tender firmware helper self-test failed."
  exit 1
fi

if ! python3 "$TENDER_PY" --download ps2 --loader "$LOADER" --plugin "$PLUGIN"; then
  record_manual "Download PS2 BIOS via Tender" <<EOF
# PluginLoader must be up, Tender signed into RomM (firmware.read).
# Then:
$ROOT/scripts/ensure-pcsx2-bios.sh
# Or Decky → Tender → System → PS2 → Download all firmware
EOF
  exit 2
fi

if [ ! -f "$PCSX2_INI" ]; then
  echo "PCSX2.ini not found at $PCSX2_INI (RetroDECK has not created it yet)."
  exit 0
fi

if ! python3 "$TENDER_PY" --pin-pcsx2 --bios-dir "$BIOS_DIR" --pcsx2-ini "$PCSX2_INI"; then
  echo "Tender downloaded firmware but no 4 MiB ps2-*.bin is visible under $BIOS_DIR"
  exit 1
fi

echo "PCSX2 BIOS is pinned from Tender's firmware cache."
exit 0
