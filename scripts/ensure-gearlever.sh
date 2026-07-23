#!/usr/bin/env bash
# Ensure Gear Lever Flatpak is installed for AppImage management.
# Uses /home (user Flatpak), so it fits SteamOS's tiny root partition.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

FLATPAK_ID="${GEARLEVER_FLATPAK_ID:-it.mijorus.gearlever}"
REMOTE="${FLATPAK_REMOTE:-flathub}"

if ! command -v flatpak >/dev/null 2>&1; then
  echo "flatpak not installed."
  record_manual "Install flatpak, then Gear Lever" <<EOF
flatpak install --user $REMOTE $FLATPAK_ID
EOF
  exit 1
fi

if flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1 || flatpak info "$FLATPAK_ID" >/dev/null 2>&1; then
  echo "Gear Lever already installed ($FLATPAK_ID)."
  flatpak info "$FLATPAK_ID" 2>/dev/null | grep -E '^(ID|Version|Installation)' || true
  exit 0
fi

# Ensure Flathub remote exists for the user.
if ! flatpak remotes --user 2>/dev/null | awk '{print $1}' | grep -Fxq "$REMOTE"; then
  if ! flatpak remotes 2>/dev/null | awk '{print $1}' | grep -Fxq "$REMOTE"; then
    echo "Adding Flatpak remote: $REMOTE"
    flatpak remote-add --user --if-not-exists "$REMOTE" "https://dl.flathub.org/repo/flathub.flatpakrepo"
  fi
fi

echo "Installing Gear Lever ($FLATPAK_ID) as user Flatpak..."
if flatpak install --user -y "$REMOTE" "$FLATPAK_ID"; then
  echo "Gear Lever installed."
  exit 0
fi

echo "Gear Lever install failed."
record_manual "Install Gear Lever Flatpak" <<EOF
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub $FLATPAK_ID
EOF
exit 1
