#!/usr/bin/env bash
# Install / refresh the Emu Pads Decky plugin (list, reorder, apply binds).
# ~/homebrew/plugins is often root-owned; copy needs sudo. Pairing is not involved.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

if ! python3 "$ROOT/scripts/bind-gamepad.py" self-test >/dev/null; then
  echo "bind-gamepad self-test failed."
  exit 1
fi

SRC="$ROOT/decky/EmuPads"
if [ ! -f "$SRC/main.py" ] || [ ! -f "$SRC/plugin.json" ] || [ ! -f "$SRC/dist/index.js" ]; then
  echo "Missing plugin files under $SRC"
  exit 1
fi

PLUGIN_DEST="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/plugins/EmuPads"
PARENT="$(dirname "$PLUGIN_DEST")"

copy_plugin() {
  mkdir -p "$PLUGIN_DEST/dist"
  cp -a "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$PLUGIN_DEST/"
  cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
}

if [ ! -d "$PARENT" ]; then
  echo "Decky plugins dir not found ($PARENT)."
  record_manual "Install Decky Loader, then Emu Pads" <<EOF
# After Decky exists:
$ROOT/scripts/ensure-emu-pads-decky.sh
EOF
  exit 2
fi

if [ -w "$PARENT" ]; then
  copy_plugin
  echo "Installed Emu Pads to $PLUGIN_DEST"
  exit 0
fi

if sudo -n true 2>/dev/null; then
  sudo mkdir -p "$PLUGIN_DEST/dist"
  sudo cp -a "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$PLUGIN_DEST/"
  sudo cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
  echo "Installed Emu Pads to $PLUGIN_DEST (sudo)"
  exit 0
fi

echo "Decky plugins dir is not writable ($PARENT)."
record_manual "Install Emu Pads Decky plugin" <<EOF
sudo mkdir -p $PLUGIN_DEST/dist
sudo cp -a $SRC/main.py $SRC/plugin.json $SRC/package.json $PLUGIN_DEST/
sudo cp -a $SRC/dist/index.js $PLUGIN_DEST/dist/index.js
# Then Decky → reload plugins (or leave Game Mode and come back).
EOF
exit 2
