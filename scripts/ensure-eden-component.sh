#!/usr/bin/env bash
# Extract the host Eden AppImage into RetroDECK's user component slot so
# ES-DE can launch it inside the Flatpak (Cemu-style), not via --host.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

# Defaults live in common.sh (EDEN_APPIMAGE = ~/AppImages/eden.appimage).
COMPONENT_DIR="$EDEN_COMPONENT_DIR"
CUSTOM_SYSTEMS="$EDEN_ES_CUSTOM_DIR"
LAUNCHER_SRC="$ROOT/scripts/eden-component/component_launcher.sh"
PATCHER_SRC="$ROOT/scripts/eden-component/patch-eden-input.py"
SYSTEMS_SRC="$ROOT/scripts/eden-component/es_systems.xml"
FIND_SRC="$ROOT/scripts/eden-component/es_find_rules.xml"

if [ ! -f "$EDEN_APPIMAGE" ]; then
  echo "Eden AppImage not found: $EDEN_APPIMAGE"
  record_manual "Place eden.appimage, then re-run ensure-eden-component" <<EOF
# Copy the AppImage to the default path, then:
$ROOT/scripts/ensure-eden-component.sh
EOF
  exit 2
fi

if [ ! -f "$LAUNCHER_SRC" ] || [ ! -f "$PATCHER_SRC" ] || [ ! -f "$ROOT/scripts/eden-component/ryubing-slot-launcher.sh" ]; then
  echo "Missing Eden component templates under $ROOT/scripts/eden-component/"
  exit 1
fi

mkdir -p "$COMPONENT_DIR" "$CUSTOM_SYSTEMS"

stamp="$COMPONENT_DIR/.extracted-from"
need_extract=1
if [ -x "$COMPONENT_DIR/AppRun" ] && [ -x "$COMPONENT_DIR/bin/eden" ] && [ -f "$stamp" ]; then
  img_m="$(stat -c %Y "$EDEN_APPIMAGE" 2>/dev/null || echo 1)"
  st_m="$(stat -c %Y "$stamp" 2>/dev/null || echo 0)"
  prev_img="$(tail -n 1 "$stamp" 2>/dev/null || true)"
  if [ "$img_m" -le "$st_m" ] && [ "$prev_img" = "$EDEN_APPIMAGE" ]; then
    need_extract=0
  fi
fi

if [ "$need_extract" -eq 1 ]; then
  echo "Extracting $EDEN_APPIMAGE into $COMPONENT_DIR"
  tmp="$(mktemp -d /tmp/eden-component-XXXXXX)"
  if ! (
    cd "$tmp" && "$EDEN_APPIMAGE" --appimage-extract
  ); then
    echo "Eden --appimage-extract failed."
    rm -rf "$tmp"
    exit 1
  fi
  src=""
  if [ -d "$tmp/AppDir" ]; then
    src="$tmp/AppDir"
  elif [ -d "$tmp/squashfs-root" ]; then
    src="$tmp/squashfs-root"
  fi
  if [ -z "$src" ]; then
    echo "Extract produced no AppDir/squashfs-root."
    rm -rf "$tmp"
    exit 1
  fi
  # Keep the previous tree until the new copy is in place. A wipe-first
  # extract left RetroDECK with no Eden if anything failed mid-copy.
  mkdir -p "$(dirname "$COMPONENT_DIR")"
  rm -rf "$COMPONENT_DIR.new" "$COMPONENT_DIR.old"
  cp -a "$src" "$COMPONENT_DIR.new"
  rm -rf "$tmp"
  if [ -d "$COMPONENT_DIR" ]; then
    mv "$COMPONENT_DIR" "$COMPONENT_DIR.old"
  fi
  mv "$COMPONENT_DIR.new" "$COMPONENT_DIR"
  rm -rf "$COMPONENT_DIR.old"
  date -Iseconds >"$stamp"
  echo "$EDEN_APPIMAGE" >>"$stamp"
  echo "Extracted Eden component ($(du -sh "$COMPONENT_DIR" | awk '{print $1}'))."
else
  echo "Eden component already extracted in $COMPONENT_DIR"
fi

install -m 0755 "$LAUNCHER_SRC" "$COMPONENT_DIR/component_launcher.sh"
install -m 0644 "$PATCHER_SRC" "$COMPONENT_DIR/patch-eden-input.py"
install -m 0644 "$SYSTEMS_SRC" "$CUSTOM_SYSTEMS/es_systems.xml"
install -m 0644 "$FIND_SRC" "$CUSTOM_SYSTEMS/es_find_rules.xml"

# Bundled linux es_systems.xml still lists Ryubing first. run_game.sh (Steam
# shortcuts without -e) uses that file, not custom_systems. Occupy the
# official RYUBING user slot with Eden so Switch games boot.
RYUBING_SLOT="$(dirname "$COMPONENT_DIR")/ryubing"
mkdir -p "$RYUBING_SLOT"
install -m 0755 "$ROOT/scripts/eden-component/ryubing-slot-launcher.sh" \
  "$RYUBING_SLOT/component_launcher.sh"

# Tender Steam shortcuts exec this file. Huge Switch dumps skip RetroDECK
# so they match standalone Game Mode (in-sandbox Eden + Flatpak OOMs).
wrap_src="$ROOT/scripts/eden-component/rom-launcher.sh"
while IFS= read -r wrap_dst; do
  [ -n "$wrap_dst" ] || continue
  install -m 0755 "$wrap_src" "$wrap_dst"
  echo "Installed host-Eden rom-launcher wrap at $wrap_dst"
done <<EOF
/home/${STEAMOS_USER}/homebrew/plugins/decky-romm-sync/bin/rom-launcher
/home/${STEAMOS_USER}/homebrew/plugins/romm-tender/bin/rom-launcher
EOF

# Eden's standalone library scans ~/emulation/switch/games. Tender dumps live
# under retrodeck/roms/switch — symlink so the same cart shows up without a copy.
emu_games="/home/${STEAMOS_USER}/emulation/switch/games"
rd_switch="/home/${STEAMOS_USER}/retrodeck/roms/switch"
if [ -d "$rd_switch" ]; then
  mkdir -p "$emu_games"
  for src in "$rd_switch"/*/; do
    [ -d "$src" ] || continue
    name="$(basename "${src%/}")"
    dest="$emu_games/$name"
    if [ ! -e "$dest" ] && [ ! -L "$dest" ]; then
      ln -sfn "${src%/}" "$dest"
      echo "Linked $dest -> $src"
    fi
  done
fi

# Bind player 0 to the pad that is present at launch (Sunshine/Xbox, then
# Steam virtual). Also run from the launcher on every game start.
eden_ini="${EDEN_QT_CONFIG:-/home/${STEAMOS_USER}/.config/eden/qt-config.ini}"
if [ -f "$eden_ini" ]; then
  python3 "$PATCHER_SRC" "$eden_ini"
fi
engage_custom="/home/${STEAMOS_USER}/.config/eden/custom/0100A6301214E000.ini"
if [ -f "$engage_custom" ]; then
  python3 "$PATCHER_SRC" --pin-4gb "$engage_custom"
fi

if ! flatpak run --command=sh net.retrodeck.retrodeck -c \
  'test -x /var/data/retrodeck/external_components/eden/component_launcher.sh && test -x /var/data/retrodeck/external_components/eden/AppRun && test -x /var/data/retrodeck/external_components/ryubing/component_launcher.sh'; then
  echo "Launcher is not visible inside the RetroDECK sandbox."
  exit 1
fi

echo "Eden is installed as a RetroDECK external component."
echo "ES-DE command: %EMULATOR_EDEN% -g %ROM%  (in-sandbox, like Cemu)"
echo "Steam/Tender Switch shortcuts without -e use the RYUBING slot (Eden)."
echo "Restart RetroDECK so ES-DE reloads custom_systems."
exit 0
