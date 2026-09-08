#!/usr/bin/env bash
# Build the FanGoH Moonlight DS debug APK. SDK/JDK must already live under /home.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SRC="${MOONLIGHT_DS_SRC:-/home/${STEAMOS_USER}/code/moonlight-android}"
JAVA_HOME="${JAVA_HOME:-/home/${STEAMOS_USER}/.local/jdk-17}"
ANDROID_HOME="${ANDROID_HOME:-/home/${STEAMOS_USER}/Android/Sdk}"
OUT_DIR="${MOONLIGHT_DS_APK_DIR:-/home/${STEAMOS_USER}/.local/share/moonlight-ds}"

if [ ! -x "$JAVA_HOME/bin/java" ]; then
  echo "Missing $JAVA_HOME/bin/java — install Temurin 17 under /home, not on /."
  exit 2
fi
if [ ! -x "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
  echo "Missing Android SDK at $ANDROID_HOME"
  exit 2
fi
if [ ! -d "$SRC/.git" ]; then
  echo "Missing $SRC — clone https://github.com/FanGoH/moonlight-android (branch dual-display)"
  exit 2
fi

export JAVA_HOME ANDROID_HOME ANDROID_SDK_ROOT="$ANDROID_HOME"
(
  cd "$SRC"
  ./gradlew :app:assembleNonRootDebug
)

mkdir -p "$OUT_DIR"
APK="$SRC/app/build/outputs/apk/nonRoot/debug/app-nonRoot-debug.apk"
install -m 0644 "$APK" "$OUT_DIR/MoonlightDS-debug.apk"
echo "Installed $OUT_DIR/MoonlightDS-debug.apk"
echo "Sideload to Thor/phone. Pair Moonlight DS to sunshine-ds on port 48100, not Decky :47989."
