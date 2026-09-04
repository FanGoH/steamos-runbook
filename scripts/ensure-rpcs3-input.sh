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
ALIAS_SRC="$ROOT/scripts/rpcs3-component/alias-rpcs3-saves.py"
GRAPHICS_SRC="$ROOT/scripts/rpcs3-component/apply-uncharted-graphics.py"
UNCHARTED_PATCH_SRC="$ROOT/scripts/rpcs3-component/uncharted-patch.yml"
FIND_SRC="$ROOT/scripts/eden-component/es_find_rules.xml"
RETRODECK_PATH="/var/data/retrodeck/bin:/app/bin:/usr/bin"
RD_RPCS3_CONFIG="${RPCS3_CONFIG_DIR:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/config/rpcs3}"
STANDALONE_RPCS3_CONFIG="/home/${STEAMOS_USER}/.config/rpcs3"

if [ ! -f "$LAUNCHER_SRC" ] || [ ! -f "$PATCHER_SRC" ] || [ ! -f "$WRAPPER_SRC" ] || [ ! -f "$ALIAS_SRC" ] || [ ! -f "$GRAPHICS_SRC" ] || [ ! -f "$UNCHARTED_PATCH_SRC" ]; then
  echo "Missing RPCS3 input templates under $ROOT/scripts/rpcs3-component/"
  exit 1
fi

mkdir -p "$COMPONENT_DIR" "$BIN_DIR" "$CUSTOM_SYSTEMS"
install -m 0755 "$LAUNCHER_SRC" "$COMPONENT_DIR/component_launcher.sh"
install -m 0644 "$PATCHER_SRC" "$COMPONENT_DIR/patch-rpcs3-input.py"
install -m 0644 "$ALIAS_SRC" "$COMPONENT_DIR/alias-rpcs3-saves.py"
install -m 0644 "$GRAPHICS_SRC" "$COMPONENT_DIR/apply-uncharted-graphics.py"
install -m 0644 "$UNCHARTED_PATCH_SRC" "$COMPONENT_DIR/uncharted-patch.yml"
install -m 0755 "$WRAPPER_SRC" "$BIN_DIR/rpcs3"

if [ -f "$FIND_SRC" ]; then
  install -m 0644 "$FIND_SRC" "$CUSTOM_SYSTEMS/es_find_rules.xml"
fi

if ! python3 "$PATCHER_SRC" --self-test; then
  echo "RPCS3 input patcher self-test failed."
  exit 1
fi
if ! python3 "$ALIAS_SRC" --self-test; then
  echo "RPCS3 save alias self-test failed."
  exit 1
fi
if ! python3 "$GRAPHICS_SRC" --self-test; then
  echo "RPCS3 Uncharted graphics self-test failed."
  exit 1
fi
if [ -f "$DEFAULT_YML" ]; then
  if ! python3 "$PATCHER_SRC" "$DEFAULT_YML"; then
    echo "Failed to patch RPCS3 Default.yml"
    exit 1
  fi
fi

# Standalone AppImage RPCS3 keeps saves in ~/.config/rpcs3. RetroDECK vfs
# points /dev_hdd0/home/00000001/savedata at ~/retrodeck/saves/ps3/rpcs3.
STANDALONE_SAVES="/home/${STEAMOS_USER}/.config/rpcs3/dev_hdd0/home/00000001/savedata"
RD_SAVES="${RPCS3_SAVES_DIR:-/home/${STEAMOS_USER}/retrodeck/saves/ps3/rpcs3}"
mkdir -p "$RD_SAVES"
if [ -d "$STANDALONE_SAVES" ]; then
  for d in "$STANDALONE_SAVES"/*; do
    [ -d "$d" ] || continue
    base="$(basename "$d")"
    case "$base" in
      _archives|_moved) continue ;;
    esac
    if [ ! -e "$RD_SAVES/$base" ]; then
      mv "$d" "$RD_SAVES/$base"
      echo "Moved standalone RPCS3 save $base into $RD_SAVES"
    else
      echo "RetroDECK already has save $base; left standalone copy in place"
    fi
  done
fi
# USA Uncharted DF disc is BCUS98103; the EBOOT lists BCES00065_NDI_UNCHARTED_DF_*
python3 "$ALIAS_SRC" "$RD_SAVES"

# Per-game 1080p / flicker / 60fps cap. Does not touch global config.yml.
if [ -d "$RD_RPCS3_CONFIG" ]; then
  python3 "$GRAPHICS_SRC" --config-dir "$RD_RPCS3_CONFIG" \
    --fallback-patch "$UNCHARTED_PATCH_SRC"
fi
if [ -d "$STANDALONE_RPCS3_CONFIG" ]; then
  python3 "$GRAPHICS_SRC" --config-dir "$STANDALONE_RPCS3_CONFIG" \
    --fallback-patch "$UNCHARTED_PATCH_SRC"
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
echo "Uncharted uses per-game 1080p / Write Color Buffers / MSAA off / 60 fps cap."
exit 0
