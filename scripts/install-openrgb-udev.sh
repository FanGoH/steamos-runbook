#!/usr/bin/env bash
# Install OpenRGB udev rules from the Flatpak export.
# SteamOS updates can remove host udev rules while keeping Flatpak apps in /home/deck.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

STATE_FILE="$STEAMOS_PLAYBOOK_DIR/logs/.openrgb-udev-installed"

if ! command -v flatpak >/dev/null 2>&1; then
  echo "flatpak not installed."
  exit 1
fi

if ! flatpak info "$OPENRGB_FLATPAK_ID" >/dev/null 2>&1; then
  echo "OpenRGB Flatpak ($OPENRGB_FLATPAK_ID) not installed."
  exit 1
fi

flatpak_path="$(flatpak info --show-location "$OPENRGB_FLATPAK_ID")"
rules_src="$flatpak_path/files/lib/udev/rules.d/60-openrgb.rules"

if [ ! -f "$rules_src" ]; then
  echo "OpenRGB udev rules not found in Flatpak export: $rules_src"
  exit 1
fi

installed=0
if [ -f "$OPENRGB_UDEV_RULES" ] && sudo cmp -s "$rules_src" "$OPENRGB_UDEV_RULES"; then
  echo "OpenRGB udev rules already up to date."
else
  sudo cp "$rules_src" "$OPENRGB_UDEV_RULES"
  sudo udevadm control --reload-rules
  sudo udevadm trigger
  installed=1
  echo "Installed OpenRGB udev rules to $OPENRGB_UDEV_RULES."
fi

mkdir -p "$(dirname "$STATE_FILE")"
if [ "$installed" -eq 1 ]; then
  date -Iseconds >"$STATE_FILE"
  echo "UDEV_CHANGED=1"
else
  echo "UDEV_CHANGED=0"
fi
