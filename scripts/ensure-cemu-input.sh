#!/usr/bin/env bash
# Bind Cemu player 0 to the pad that is plugged in at launch (same pick as Eden).
# Wraps bundled Cemu without copying it into the Flatpak files dir.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

COMPONENT_DIR="${CEMU_COMPONENT_DIR:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/retrodeck/external_components/cemu}"
BIN_DIR="${CEMU_WRAPPER_BIN_DIR:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/retrodeck/bin}"
CUSTOM_SYSTEMS="${EDEN_ES_CUSTOM_DIR:-/home/${STEAMOS_USER}/retrodeck/ES-DE/custom_systems}"
CONTROLLER_XML="${CEMU_CONTROLLER_XML:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/config/Cemu/controllerProfiles/controller0.xml}"
LAUNCHER_SRC="$ROOT/scripts/cemu-component/component_launcher.sh"
WRAPPER_SRC="$ROOT/scripts/cemu-component/Cemu-wrapper"
PATCHER_SRC="$ROOT/scripts/cemu-component/patch-cemu-input.py"
FIND_SRC="$ROOT/scripts/eden-component/es_find_rules.xml"
RETRODECK_PATH="/var/data/retrodeck/bin:/app/bin:/usr/bin"

if [ ! -f "$LAUNCHER_SRC" ] || [ ! -f "$PATCHER_SRC" ] || [ ! -f "$WRAPPER_SRC" ]; then
  echo "Missing Cemu input templates under $ROOT/scripts/cemu-component/"
  exit 1
fi

mkdir -p "$COMPONENT_DIR" "$BIN_DIR" "$CUSTOM_SYSTEMS"
install -m 0755 "$LAUNCHER_SRC" "$COMPONENT_DIR/component_launcher.sh"
install -m 0644 "$PATCHER_SRC" "$COMPONENT_DIR/patch-cemu-input.py"
install -m 0755 "$WRAPPER_SRC" "$BIN_DIR/Cemu-wrapper"

if [ -f "$FIND_SRC" ]; then
  install -m 0644 "$FIND_SRC" "$CUSTOM_SYSTEMS/es_find_rules.xml"
fi

if ! python3 "$PATCHER_SRC" --self-test; then
  echo "Cemu input patcher self-test failed."
  exit 1
fi
if [ -f "$CONTROLLER_XML" ]; then
  python3 "$PATCHER_SRC" "$CONTROLLER_XML"
fi

# Steam/Tender uses run_game.sh, which only reads bundled find-rules. Those
# list systempath Cemu-wrapper before the /app Cemu launcher. Prepend our bin
# so command -v Cemu-wrapper succeeds inside the sandbox.
if command -v flatpak >/dev/null 2>&1; then
  if flatpak override --user --show net.retrodeck.retrodeck 2>/dev/null | grep -q '/var/data/retrodeck/bin'; then
    echo "RetroDECK PATH already includes /var/data/retrodeck/bin"
  else
    flatpak override --user net.retrodeck.retrodeck --env=PATH="$RETRODECK_PATH"
    echo "Set RetroDECK PATH so Cemu-wrapper is found before bundled Cemu."
  fi
fi

if ! flatpak run --command=sh net.retrodeck.retrodeck -c \
  'test -x /var/data/retrodeck/external_components/cemu/component_launcher.sh && test -x "$(command -v Cemu-wrapper)"'; then
  echo "Cemu wrapper is not visible inside the RetroDECK sandbox."
  exit 1
fi

echo "Cemu player 0 is rebound to the current pad on each launch."
exit 0
