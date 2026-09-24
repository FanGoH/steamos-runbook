#!/usr/bin/env bash
# Install / refresh the Switch 2 (NUXBT) Decky plugin.
# ~/homebrew/plugins is often root-owned; copy needs sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SRC="$ROOT/decky/Switch2"
if [ ! -f "$SRC/main.py" ] || [ ! -f "$SRC/plugin.json" ] || [ ! -f "$SRC/dist/index.js" ]; then
  echo "Missing plugin files under $SRC"
  exit 1
fi
if [ ! -f "$ROOT/scripts/nuxbt-api.py" ]; then
  echo "Missing scripts/nuxbt-api.py"
  exit 1
fi

PLUGIN_DEST="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/plugins/Switch2"
SNAPSHOT="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/data/Switch2"
PARENT="$(dirname "$PLUGIN_DEST")"
PLUGIN_NAME="$(python3 -c "import json; print(json.load(open('$SRC/plugin.json'))['name'])")"

snapshot_backend() {
  mkdir -p "$SNAPSHOT/scripts" "$SNAPSHOT/logs"
  cp -a "$ROOT/scripts/nuxbt-api.py" "$SNAPSHOT/scripts/"
  cp -a "$ROOT/scripts/nuxbt-bridge.sh" "$SNAPSHOT/scripts/" 2>/dev/null || true
  cp -a "$ROOT/scripts/nuxbt-sunshine-bridge.py" "$SNAPSHOT/scripts/" 2>/dev/null || true
}

snapshot_backend || true

finish_install() {
  echo "$1"
  if decky_reload_plugin "$PLUGIN_NAME"; then
    echo "Reloaded $PLUGIN_NAME in Decky (close and reopen QAM if it is already open)."
  else
    echo "Copied files; reload Decky plugins (or leave Game Mode and come back) to see the new QAM UI."
  fi
  exit 0
}

copy_plugin() {
  mkdir -p "$PLUGIN_DEST/dist"
  cp -a "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$PLUGIN_DEST/"
  cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
}

if [ ! -d "$PARENT" ]; then
  echo "Decky plugins dir not found ($PARENT)."
  record_manual "Install Decky Loader, then Switch 2 plugin" <<EOF
# After Decky exists:
$ROOT/scripts/ensure-switch2-decky.sh
EOF
  exit 2
fi

if [ -w "$PARENT" ]; then
  copy_plugin
  finish_install "Installed Switch 2 to $PLUGIN_DEST"
fi

if [ -w "$PLUGIN_DEST/main.py" ] && [ -w "$PLUGIN_DEST/dist/index.js" ]; then
  cp -a "$SRC/main.py" "$PLUGIN_DEST/main.py"
  cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
  [ -w "$PLUGIN_DEST/plugin.json" ] && cp -a "$SRC/plugin.json" "$PLUGIN_DEST/plugin.json"
  [ -w "$PLUGIN_DEST/package.json" ] && cp -a "$SRC/package.json" "$PLUGIN_DEST/package.json"
  finish_install "Updated writable Switch 2 files in $PLUGIN_DEST"
fi

if sudo -n true 2>/dev/null; then
  sudo mkdir -p "$PLUGIN_DEST/dist"
  sudo cp -a "$SRC/main.py" "$SRC/plugin.json" "$SRC/package.json" "$PLUGIN_DEST/"
  sudo cp -a "$SRC/dist/index.js" "$PLUGIN_DEST/dist/index.js"
  finish_install "Installed Switch 2 to $PLUGIN_DEST (sudo)"
fi

echo "Decky plugins dir is not writable ($PARENT)."
record_manual "Install Switch 2 Decky plugin" <<EOF
sudo mkdir -p $PLUGIN_DEST/dist
sudo cp -a $SRC/main.py $SRC/plugin.json $SRC/package.json $PLUGIN_DEST/
sudo cp -a $SRC/dist/index.js $PLUGIN_DEST/dist/index.js
# Then Decky → reload plugins (or leave Game Mode and come back).
EOF
exit 2
