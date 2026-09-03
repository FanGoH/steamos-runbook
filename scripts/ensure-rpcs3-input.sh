#!/usr/bin/env bash
# Bind RPCS3 player 1 to the pad that is plugged in at launch (same pick as
# Eden/Cemu). RetroDECK ships Device=Steam Deck Controller 1; this box is not
# a Deck, so Uncharted reports no Sixaxis until Device matches a present pad.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

COMPONENT_DIR="${RPCS3_COMPONENT_DIR:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/retrodeck/external_components/rpcs3}"
BIN_DIR="${RPCS3_WRAPPER_BIN_DIR:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/retrodeck/bin}"
CUSTOM_SYSTEMS="${EDEN_ES_CUSTOM_DIR:-/home/${STEAMOS_USER}/retrodeck/ES-DE/custom_systems}"
DEFAULT_YML="${RPCS3_DEFAULT_YML:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/config/rpcs3/input_configs/global/Default.yml}"
LAUNCHER_SRC="$ROOT/scripts/rpcs3-component/component_launcher.sh"
WRAPPER_SRC="$ROOT/scripts/rpcs3-component/rpcs3-wrapper"
PATCHER_SRC="$ROOT/scripts/rpcs3-component/patch-rpcs3-input.py"
FIND_SRC="$ROOT/scripts/eden-component/es_find_rules.xml"
RETRODECK_PATH="/var/data/retrodeck/bin:/app/bin:/usr/bin"

if [ ! -f "$LAUNCHER_SRC" ] || [ ! -f "$PATCHER_SRC" ] || [ ! -f "$WRAPPER_SRC" ]; then
  echo "Missing RPCS3 input templates under $ROOT/scripts/rpcs3-component/"
  exit 1
fi

mkdir -p "$COMPONENT_DIR" "$BIN_DIR" "$CUSTOM_SYSTEMS"
install -m 0755 "$LAUNCHER_SRC" "$COMPONENT_DIR/component_launcher.sh"
install -m 0644 "$PATCHER_SRC" "$COMPONENT_DIR/patch-rpcs3-input.py"
install -m 0755 "$WRAPPER_SRC" "$BIN_DIR/rpcs3"

if [ -f "$FIND_SRC" ]; then
  install -m 0644 "$FIND_SRC" "$CUSTOM_SYSTEMS/es_find_rules.xml"
fi

if ! python3 "$PATCHER_SRC" --self-test; then
  echo "RPCS3 input patcher self-test failed."
  exit 1
fi
if [ -f "$DEFAULT_YML" ]; then
  if ! python3 "$PATCHER_SRC" "$DEFAULT_YML"; then
    echo "Failed to patch RPCS3 Default.yml"
    exit 1
  fi
fi

# Steam/Tender uses run_game.sh, which only reads bundled find-rules. Those
# list systempath `rpcs3` before the /app RPCS3 launcher. Prepend our bin
# so command -v rpcs3 hits the pad-binding wrapper. SDL3 also needs the
# Steam-virtual allow env on every RetroDECK process, even if a launch
# skips this wrapper.
if command -v flatpak >/dev/null 2>&1; then
  if flatpak override --user --show net.retrodeck.retrodeck 2>/dev/null | grep -q '/var/data/retrodeck/bin'; then
    echo "RetroDECK PATH already includes /var/data/retrodeck/bin"
  else
    flatpak override --user net.retrodeck.retrodeck --env=PATH="$RETRODECK_PATH"
    echo "Set RetroDECK PATH so rpcs3 is found before bundled RPCS3."
  fi
  if flatpak override --user --show net.retrodeck.retrodeck 2>/dev/null \
    | grep -q 'SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1'; then
    echo "RetroDECK already allows the Steam virtual gamepad"
  else
    flatpak override --user net.retrodeck.retrodeck \
      --env=SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
    echo "Set RetroDECK SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1"
  fi
fi

if ! flatpak run --command=sh net.retrodeck.retrodeck -c \
  'test -x /var/data/retrodeck/external_components/rpcs3/component_launcher.sh && test "$(command -v rpcs3)" = /var/data/retrodeck/bin/rpcs3'; then
  echo "RPCS3 wrapper is not visible inside the RetroDECK sandbox."
  exit 1
fi

echo "RPCS3 player 1 is rebound to the current pad on each launch."
exit 0
