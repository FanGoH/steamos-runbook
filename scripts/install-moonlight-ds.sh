#!/usr/bin/env bash
# Sideload Moonlight DS debug APK. Do not adb kill-server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

ANDROID_HOME="${ANDROID_HOME:-/home/${STEAMOS_USER}/Android/Sdk}"
ADB="${ADB:-$ANDROID_HOME/platform-tools/adb}"
APK="${MOONLIGHT_DS_APK:-/home/${STEAMOS_USER}/.local/share/moonlight-ds/MoonlightDS-debug.apk}"

if [ ! -x "$ADB" ]; then
  echo "Missing adb at $ADB"
  exit 2
fi
if [ ! -f "$APK" ]; then
  echo "Missing $APK — run ./scripts/build-moonlight-ds.sh first."
  exit 1
fi

# Optional space-separated serials or host:port from .env (same as FGPC).
for spec in ${FGPC_APK_ADB:-}; do
  "$ADB" connect "$spec" >/dev/null || true
done

mapfile -t serials < <("$ADB" devices | awk 'NR>1 && $2=="device" {print $1}')
if [ "${#serials[@]}" -eq 0 ]; then
  echo "No ADB devices. Enable wireless debugging, then:"
  echo "  $ADB connect HOST:PORT"
  echo "  FGPC_APK_ADB=HOST:PORT ./scripts/install-moonlight-ds.sh Portal"
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
echo "Installed Moonlight DS on $ok device(s). Pair to sunshine-ds :48200, not Decky :47989."
