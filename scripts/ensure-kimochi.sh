#!/usr/bin/env bash
# Wrap Kimochi's Steam Game Mode launcher so the AppImage can find
# fusermount. Steam's existing shortcut stays pointed at
# ~/.local/share/kimochi/gaming-mode/launch.sh — do not rewrite
# shortcuts.vdf while Game Mode is running. Kimochi updates restore
# launch.sh; re-run this (also from post-update.sh).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
if ! require_playbook_user; then
  exit 2
fi

LAUNCHER="$ROOT/scripts/kimochi-gaming-mode.sh"
KIMOCHI_ROOT="${KIMOCHI_GAMING_MODE_ROOT:-/home/${STEAMOS_USER}/.local/share/kimochi/gaming-mode}"
WRAP="$KIMOCHI_ROOT/launch.sh"
APPIMAGE="${KIMOCHI_APPIMAGE:-/home/${STEAMOS_USER}/.local/share/kimochi/Kimochi.AppImage}"
MARK="steamos-playbook kimochi-gaming-mode wrap"

chmod +x "$LAUNCHER" 2>/dev/null || true

if [ ! -e "$APPIMAGE" ] && [ ! -e "$KIMOCHI_ROOT/current/Kimochi.AppImage" ]; then
  echo "Kimochi AppImage not installed; skip Game Mode wrap."
  exit 0
fi

if [ ! -d "$KIMOCHI_ROOT/current" ] || [ ! -f "$KIMOCHI_ROOT/current/scripts/launch-from-steam.sh" ]; then
  echo "Kimochi Gaming Mode files missing under $KIMOCHI_ROOT"
  record_manual "Install Kimochi Gaming Mode, then wrap the Steam launcher" <<EOF
# From Kimochi: enable Gaming Mode, then:
$ROOT/scripts/ensure-kimochi.sh
EOF
  exit 2
fi

if [ ! -x "$LAUNCHER" ]; then
  echo "Missing $LAUNCHER"
  exit 1
fi

desired=$(cat <<EOF
#!/bin/sh
# $MARK
# Steam Game Mode PATH has no fusermount. Restore via $ROOT/scripts/ensure-kimochi.sh.
exec /bin/sh '$LAUNCHER' "\$@"
EOF
)

mkdir -p "$KIMOCHI_ROOT"
if [ -f "$WRAP" ] && [ "$(cat "$WRAP")" = "$desired" ]; then
  echo "Kimochi Game Mode wrap already in place ($WRAP)."
else
  printf '%s\n' "$desired" >"$WRAP"
  chmod +x "$WRAP"
  echo "Wrapped Kimochi Steam launcher: $WRAP -> $LAUNCHER"
  echo "Existing Steam tile keeps LaunchOptions=$WRAP (no shortcuts.vdf rewrite)."
fi

# 0.8.1 radial menu: extract AppDir and patch !deck.connected() cancel.
# Empty/placeholder AppImages (offline tests) are skipped.
PATCHER="$ROOT/scripts/patch-kimochi-controller-nav.py"
EXTRACT="$KIMOCHI_ROOT/extracted"
real_app="$APPIMAGE"
if [ ! -e "$real_app" ]; then
  real_app="$KIMOCHI_ROOT/current/Kimochi.AppImage"
fi
app_size=0
if [ -e "$real_app" ]; then
  app_size=$(stat -c%s "$real_app" 2>/dev/null || echo 0)
fi
if [ -f "$PATCHER" ] && [ "${app_size:-0}" -gt 1000000 ]; then
  if [ ! -x "$EXTRACT/usr/bin/kimochi" ] || [ "$real_app" -nt "$EXTRACT/usr/bin/kimochi" ]; then
    tmp=$(mktemp -d)
    if (CDPATH= cd -- "$tmp" && PATH="/usr/bin:/bin:${PATH:-}" "$real_app" --appimage-extract); then
      rm -rf "$EXTRACT"
      mv "$tmp/squashfs-root" "$EXTRACT"
      chmod -R u+w "$EXTRACT" 2>/dev/null || true
      echo "Extracted Kimochi AppDir for controller-nav patch: $EXTRACT"
    else
      echo "Could not extract Kimochi AppImage for controller-nav patch."
    fi
    rm -rf "$tmp"
  fi
  if [ -x "$EXTRACT/usr/bin/kimochi" ]; then
    /usr/bin/python3 "$PATCHER" --elf "$EXTRACT/usr/bin/kimochi" || true
  fi
fi
exit 0
