#!/usr/bin/env bash
# Apply Wake-on-LAN on the configured NIC. Called by wol.service after SteamOS updates.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if [ ! -d "/sys/class/net/$STEAMOS_NIC_INTERFACE" ]; then
  echo "NIC $STEAMOS_NIC_INTERFACE not found."
  exit 1
fi

if ! command -v ethtool >/dev/null 2>&1; then
  echo "ethtool missing."
  exit 1
fi

/usr/bin/ethtool -s "$STEAMOS_NIC_INTERFACE" wol g

current_wol="$(nic_wake_on "$STEAMOS_NIC_INTERFACE")"
# Normalize whitespace
current_wol="$(printf '%s' "$current_wol" | tr -d '[:space:]')"
if [ "$current_wol" = "g" ]; then
  echo "Wake-on-LAN enabled on $STEAMOS_NIC_INTERFACE."
else
  echo "Failed to enable Wake-on-LAN on $STEAMOS_NIC_INTERFACE (Wake-on: ${current_wol:-unknown})."
  exit 1
fi
