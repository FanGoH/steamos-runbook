#!/usr/bin/env bash
# Install / refresh the Emu Quick Decky plugin (Eden / Azahar / Cemu settings).
# ~/homebrew/plugins is often root-owned; copy needs sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if ! python3 "$ROOT/scripts/test_emu_quick_settings.py" >/dev/null; then
  echo "emu-quick-settings tests failed."
  exit 1
fi

SRC="$ROOT/decky/EmuQuick"
if [ ! -f "$SRC/main.py" ] || [ ! -f "$SRC/plugin.json" ] || [ ! -f "$SRC/dist/index.js" ]; then
  echo "Missing plugin files under $SRC"
  exit 1
fi

PLUGIN_DEST="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/plugins/EmuQuick"
PARENT="$(dirname "$PLUGIN_DEST")"

copy_plugin() {
  mkdir -p "$PLUGIN_DEST/dist"
  cp -a "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$PLUGIN_DEST/"
  cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
}

if [ ! -d "$PARENT" ]; then
  echo "Decky plugins dir not found ($PARENT)."
  record_manual "Install Decky Loader, then Emu Quick" <<EOF
# After Decky exists:
$ROOT/scripts/ensure-emu-quick-decky.sh
EOF
  exit 2
fi

if [ -w "$PARENT" ]; then
  copy_plugin
  echo "Installed Emu Quick to $PLUGIN_DEST"
  exit 0
fi

if [ -w "$PLUGIN_DEST/main.py" ] && [ -w "$PLUGIN_DEST/dist/index.js" ]; then
  cp -a "$SRC/main.py" "$PLUGIN_DEST/main.py"
  cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
  [ -w "$PLUGIN_DEST/plugin.json" ] && cp -a "$SRC/plugin.json" "$PLUGIN_DEST/plugin.json"
  [ -w "$PLUGIN_DEST/package.json" ] && cp -a "$SRC/package.json" "$PLUGIN_DEST/package.json"
  echo "Updated writable Emu Quick files in $PLUGIN_DEST"
  exit 0
fi

if sudo -n true 2>/dev/null; then
  sudo mkdir -p "$PLUGIN_DEST/dist"
  sudo cp -a "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$PLUGIN_DEST/"
  sudo cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
  echo "Installed Emu Quick to $PLUGIN_DEST (sudo)"
  exit 0
fi

echo "Decky plugins dir is not writable ($PARENT)."
record_manual "Install Emu Quick Decky plugin" <<EOF
sudo mkdir -p $PLUGIN_DEST/dist
sudo cp -a $SRC/main.py $SRC/plugin.json $SRC/package.json $PLUGIN_DEST/
sudo cp -a $SRC/dist/index.js $PLUGIN_DEST/dist/index.js
# Then Decky → reload plugins (or leave Game Mode and come back).
EOF
exit 2
