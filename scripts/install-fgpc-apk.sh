#!/usr/bin/env bash
# Sideload FGPC.apk. Do not adb kill-server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

ANDROID_HOME="${ANDROID_HOME:-/home/${STEAMOS_USER}/Android/Sdk}"
ADB="${ADB:-$ANDROID_HOME/platform-tools/adb}"
APK="${FGPC_APK:-/home/${STEAMOS_USER}/.local/share/fgpc/FGPC.apk}"

if [ ! -x "$ADB" ]; then
  echo "Missing adb at $ADB"
  exit 2
fi
if [ ! -f "$APK" ]; then
  echo "Missing $APK — run ./scripts/build-fgpc-apk.sh first."
  exit 1
fi

# Optional space-separated serials or host:port from .env
# Example: FGPC_APK_ADB="192.168.68.56:40143 192.168.68.57:35999"
for spec in ${FGPC_APK_ADB:-}; do
  "$ADB" connect "$spec" >/dev/null || true
done

mapfile -t serials < <("$ADB" devices | awk 'NR>1 && $2=="device" {print $1}')
if [ "${#serials[@]}" -eq 0 ]; then
  echo "No ADB devices. Enable wireless debugging on the phone/Odin, then:"
  echo "  $ADB connect HOST:PORT"
  echo "  FGPC_APK_ADB=HOST:PORT ./scripts/install-fgpc-apk.sh"
  exit 2
fi

want="${1:-}"
ok=0
for serial in "${serials[@]}"; do
  model="$("$ADB" -s "$serial" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
  echo "Installing on $serial ($model)"
  if [ -n "$want" ] && ! echo "$serial $model" | grep -qi "$want"; then
    echo "  skip (filter $want)"
    continue
  fi
  "$ADB" -s "$serial" install -r -t "$APK"
  ok=$((ok + 1))
done

if [ "$ok" -eq 0 ]; then
  echo "No matching device installed."
  exit 2
fi
echo "Installed FGPC on $ok device(s). Open the FGPC icon (HTTP WebView, Tailscale up)."
