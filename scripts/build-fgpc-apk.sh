#!/usr/bin/env bash
# Build the thin FGPC WebView APK (server-driven UI on :8484).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SRC="$ROOT/fgpc/android"
JAVA_HOME="${JAVA_HOME:-/home/${STEAMOS_USER}/.local/jdk-17}"
ANDROID_HOME="${ANDROID_HOME:-/home/${STEAMOS_USER}/Android/Sdk}"
OUT_DIR="${FGPC_APK_DIR:-/home/${STEAMOS_USER}/.local/share/fgpc}"

if [ ! -x "$JAVA_HOME/bin/java" ]; then
  echo "Missing $JAVA_HOME/bin/java — install Temurin 17 under /home, not on /."
  exit 2
fi
if [ ! -x "$ANDROID_HOME/platform-tools/adb" ]; then
  echo "Missing Android SDK at $ANDROID_HOME"
  exit 2
fi
if [ ! -x "$SRC/gradlew" ]; then
  echo "Missing $SRC/gradlew"
  exit 1
fi

printf 'sdk.dir=%s\n' "$ANDROID_HOME" >"$SRC/local.properties"

export JAVA_HOME ANDROID_HOME ANDROID_SDK_ROOT="$ANDROID_HOME"
(
  cd "$SRC"
  ./gradlew :app:assembleDebug --no-daemon
)

mkdir -p "$OUT_DIR"
APK="$SRC/app/build/outputs/apk/debug/app-debug.apk"
install -m 0644 "$APK" "$OUT_DIR/FGPC.apk"
echo "Built $OUT_DIR/FGPC.apk"
echo "Sideload: ./scripts/install-fgpc-apk.sh"
echo "The APK is a WebView for http://fgpc.tailnet.fangoh.dev:8484/ (HTTP, not https)."
