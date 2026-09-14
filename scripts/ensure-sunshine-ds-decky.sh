#!/usr/bin/env bash
# Install the Sunshine DS Decky plugin (Game Mode → Plasma + proven :48100).
# Plugins dir is often root-owned; then print the sudo copy. Does not switch sessions.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SRC="$ROOT/decky/sunshine-ds"
PLUGIN_NAME="${SUNSHINE_DS_DECKY_PLUGIN:-SunshineDS}"
PLUGINS_DIR="${DECKY_HOMEBREW_DIR:-/home/${STEAMOS_USER:-deck}/homebrew}/plugins"
DEST="$PLUGINS_DIR/$PLUGIN_NAME"

if [ ! -f "$SRC/main.py" ] || [ ! -f "$SRC/dist/index.js" ] || [ ! -f "$SRC/plugin.json" ]; then
  echo "Decky plugin source incomplete under $SRC"
  exit 1
fi

ZIP="$ROOT/decky/SunshineDS.zip"
make_zip() {
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "$tmp/$PLUGIN_NAME/dist"
  cp -f "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$tmp/$PLUGIN_NAME/"
  cp -f "$SRC/dist/index.js" "$tmp/$PLUGIN_NAME/dist/index.js"
  rm -f "$ZIP"
  (cd "$tmp" && zip -qr "$ZIP" "$PLUGIN_NAME")
  rm -rf "$tmp"
  echo "Packaged $ZIP"
}

make_zip
chmod +x "$ROOT/scripts/sunshine-ds-on-desktop.sh" \
  "$ROOT/scripts/switch-to-desktop-ds.sh" \
  "$ROOT/scripts/sunshine-app-game-mode.sh"
bash "$ROOT/scripts/ensure-sunshine-ds.sh" --install-shortcut || true
bash "$ROOT/scripts/ensure-sunshine-ds-apps.sh" || true

install_files() {
  local dest="$1"
  mkdir -p "$dest/dist"
  cp -f "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$dest/"
  cp -f "$SRC/dist/index.js" "$dest/dist/index.js"
}

if [ ! -d "$PLUGINS_DIR" ]; then
  echo "Decky plugins dir missing ($PLUGINS_DIR)."
  exit 2
fi

if [ -w "$PLUGINS_DIR" ]; then
  install_files "$DEST"
  echo "Installed Decky plugin $DEST"
  echo "Game Mode: Quick Access → Decky → Sunshine DS → Start Dual-Stream Desktop"
  echo "Restart PluginLoader if the tile is missing."
  exit 0
fi

if sudo -n true 2>/dev/null; then
  sudo mkdir -p "$DEST/dist"
  sudo cp -f "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$DEST/"
  sudo cp -f "$SRC/dist/index.js" "$DEST/dist/index.js"
  echo "Installed Decky plugin $DEST (sudo)."
  echo "Game Mode: Quick Access → Decky → Sunshine DS → Start Dual-Stream Desktop"
  echo "Restart PluginLoader if the tile is missing."
  exit 0
fi

echo "Decky plugins dir is not writable."
record_manual "Install Sunshine DS Decky plugin" <<EOF
# Copy into Decky (plugins dir is root-owned):
sudo mkdir -p $DEST/dist
sudo cp -f $SRC/main.py $SRC/plugin.json $SRC/package.json $DEST/
sudo cp -f $SRC/dist/index.js $DEST/dist/index.js
# Or Decky → Settings → Developer → Install plugin from zip:
#   $ZIP
# Then reload PluginLoader. Game Mode: Quick Access → Decky → Sunshine DS.
EOF
exit 2
