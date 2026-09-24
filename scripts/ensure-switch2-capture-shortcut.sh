#!/usr/bin/env bash
# Install a Steam non-Steam shortcut that fullscreen-views the Switch 2 capture card.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

VIEWER="$ROOT/scripts/switch2-capture-viewer.sh"
MPV_ENSURE="$ROOT/scripts/ensure-switch2-mpv.sh"
APPS_DIR="/home/${STEAMOS_USER}/.local/share/applications"
DESKTOP_DIR="/home/${STEAMOS_USER}/Desktop"
APP_ID="steamos-switch2-capture"
APPS_FILE="$APPS_DIR/${APP_ID}.desktop"
DESKTOP_FILE="$DESKTOP_DIR/Nintendo Switch 2.desktop"
NAME="Nintendo Switch 2"

chmod +x "$VIEWER" "$MPV_ENSURE"
# Host mpv AppImage (Flatpak cannot open MS2109 V4L2 ACLs).
"$MPV_ENSURE" || record_manual "Download mpv AppImage: $MPV_ENSURE"
mkdir -p "$APPS_DIR" "$DESKTOP_DIR"

cat >"$APPS_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$NAME
Comment=Fullscreen HDMI capture + audio (MacroSilicon MS2109 via mpv)
Exec=$VIEWER
TryExec=$VIEWER
Path=$ROOT
Icon=input-gaming
Terminal=false
StartupNotify=false
Categories=Game;
Keywords=switch;capture;hdmi;moonlight;nuxbt;mpv;
EOF
chmod +x "$APPS_FILE"
cp -f "$APPS_FILE" "$DESKTOP_FILE"
chmod +x "$DESKTOP_FILE"
if command -v gio >/dev/null 2>&1; then
  gio set "$DESKTOP_FILE" metadata::trusted true 2>/dev/null || true
fi

echo "Installed desktop entry: $APPS_FILE"

ADD_BIN=""
if command -v steamos-add-to-steam >/dev/null 2>&1; then
  ADD_BIN=steamos-add-to-steam
elif command -v holo-add-to-steam >/dev/null 2>&1; then
  ADD_BIN=holo-add-to-steam
fi

if [ -z "$ADD_BIN" ]; then
  record_manual "Add Non-Steam Game manually: $APPS_FILE (or $VIEWER)"
  echo "warn: steamos-add-to-steam not found — add $APPS_FILE in Steam manually"
  exit 2
fi

# Prefer the applications entry so Steam gets a stable Name/Icon.
if "$ADD_BIN" "$APPS_FILE"; then
  echo "Added to Steam via $ADD_BIN: $NAME"
else
  record_manual "steamos-add-to-steam failed — Add Non-Steam Game: $APPS_FILE"
  echo "warn: $ADD_BIN failed for $APPS_FILE"
  exit 2
fi

# Confirm shortcut name appears (may lag until Steam refreshes).
if grep -a -F "$NAME" /home/"${STEAMOS_USER}"/.local/share/Steam/userdata/*/config/shortcuts.vdf >/dev/null 2>&1; then
  echo "shortcuts.vdf already lists: $NAME"
else
  echo "note: Steam may list '$NAME' after a library refresh (Game Mode rewrites shortcuts.vdf live)."
fi

echo "Launch: Steam → Non-Steam → $NAME  (or: $VIEWER)"
