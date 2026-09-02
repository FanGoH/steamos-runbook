#!/usr/bin/env bash
# Extract the host Eden AppImage into RetroDECK's user component slot so
# ES-DE can launch it inside the Flatpak (Cemu-style), not via --host.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

EDEN_APPIMAGE="${EDEN_APPIMAGE:-/home/${STEAMOS_USER}/Applications/Eden.appimage}"
COMPONENT_DIR="${EDEN_COMPONENT_DIR:-/home/${STEAMOS_USER}/.var/app/net.retrodeck.retrodeck/data/retrodeck/external_components/eden}"
CUSTOM_SYSTEMS="${EDEN_ES_CUSTOM_DIR:-/home/${STEAMOS_USER}/retrodeck/ES-DE/custom_systems}"
LAUNCHER_SRC="$ROOT/scripts/eden-component/component_launcher.sh"
SYSTEMS_SRC="$ROOT/scripts/eden-component/es_systems.xml"
FIND_SRC="$ROOT/scripts/eden-component/es_find_rules.xml"

if [ ! -f "$EDEN_APPIMAGE" ]; then
  echo "Eden AppImage not found: $EDEN_APPIMAGE"
  record_manual "Place Eden.appimage, then re-run ensure-eden-component" <<EOF
# Copy the AppImage to the default path, then:
$ROOT/scripts/ensure-eden-component.sh
EOF
  exit 2
fi

if [ ! -f "$LAUNCHER_SRC" ]; then
  echo "Missing launcher template: $LAUNCHER_SRC"
  exit 1
fi

mkdir -p "$COMPONENT_DIR" "$CUSTOM_SYSTEMS"

stamp="$COMPONENT_DIR/.extracted-from"
need_extract=1
if [ -x "$COMPONENT_DIR/AppRun" ] && [ -x "$COMPONENT_DIR/bin/eden" ] && [ -f "$stamp" ]; then
  img_m="$(stat -c %Y "$EDEN_APPIMAGE" 2>/dev/null || echo 1)"
  st_m="$(stat -c %Y "$stamp" 2>/dev/null || echo 0)"
  if [ "$img_m" -le "$st_m" ]; then
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
  rm -rf "$COMPONENT_DIR"
  mkdir -p "$(dirname "$COMPONENT_DIR")"
  cp -a "$src" "$COMPONENT_DIR"
  rm -rf "$tmp"
  date -Iseconds >"$stamp"
  echo "$EDEN_APPIMAGE" >>"$stamp"
  echo "Extracted Eden component ($(du -sh "$COMPONENT_DIR" | awk '{print $1}'))."
else
  echo "Eden component already extracted in $COMPONENT_DIR"
fi

install -m 0755 "$LAUNCHER_SRC" "$COMPONENT_DIR/component_launcher.sh"
install -m 0644 "$SYSTEMS_SRC" "$CUSTOM_SYSTEMS/es_systems.xml"
install -m 0644 "$FIND_SRC" "$CUSTOM_SYSTEMS/es_find_rules.xml"

# Host Eden was bound to the physical Xbox GUID. Steam keeps that device
# for overlay and exposes a virtual pad (Cemu SteamInput-P1). Drop the GUID
# so player 1 follows SDL port 0 (the virtual pad).
eden_ini="${EDEN_QT_CONFIG:-/home/${STEAMOS_USER}/.config/eden/qt-config.ini}"
xbox_guid="030000005e040000ea02000008040000"
if [ -f "$eden_ini" ] && grep -q "$xbox_guid" "$eden_ini"; then
  python3 - "$eden_ini" "$xbox_guid" <<'PY'
from pathlib import Path
import sys
p, guid = Path(sys.argv[1]), sys.argv[2]
text = p.read_text()
needle = f",guid:{guid}"
if needle not in text:
    raise SystemExit(0)
bak = p.with_suffix(p.suffix + ".bak-steam-virtual")
if not bak.exists():
    bak.write_text(text)
out = []
for line in text.splitlines(keepends=True):
    if line.startswith("player_0_") and guid in line:
        line = line.replace(needle, "")
    out.append(line)
p.write_text("".join(out))
print(f"Unbound player 0 from physical Xbox GUID in {p}")
PY
fi

if ! flatpak run --command=sh net.retrodeck.retrodeck -c \
  'test -x /var/data/retrodeck/external_components/eden/component_launcher.sh && test -x /var/data/retrodeck/external_components/eden/AppRun'; then
  echo "Launcher is not visible inside the RetroDECK sandbox."
  exit 1
fi

echo "Eden is installed as a RetroDECK external component."
echo "ES-DE command: %EMULATOR_EDEN% -g %ROM%  (in-sandbox, like Cemu)"
echo "Restart RetroDECK so ES-DE reloads custom_systems."
exit 0
