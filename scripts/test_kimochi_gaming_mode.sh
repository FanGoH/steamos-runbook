#!/usr/bin/env bash
# Offline checks for the Kimochi Game Mode AppImage wrap (no GUI start).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

LAUNCHER="$ROOT/scripts/kimochi-gaming-mode.sh"
ENSURE="$ROOT/scripts/ensure-kimochi.sh"

[ -x "$LAUNCHER" ] || fail "kimochi-gaming-mode.sh not executable"
[ -x "$ENSURE" ] || fail "ensure-kimochi.sh not executable"

grep -q 'PATH="/usr/bin:/bin:' "$LAUNCHER" || fail "launcher must prepend /usr/bin:/bin"
grep -q 'FUSERMOUNT_PROG' "$LAUNCHER" || fail "launcher must set FUSERMOUNT_PROG"
grep -q 'launch-from-steam.sh' "$LAUNCHER" || fail "launcher must exec Kimochi's launch-from-steam.sh"
if grep -qE 'pgrep -f|pkill -f' "$LAUNCHER" "$ENSURE"; then
  fail "must not pgrep -f / pkill -f"
fi
grep -q 'shortcuts.vdf' "$ENSURE" || fail "ensure-kimochi.sh must document no shortcuts.vdf rewrite"
grep -q 'kimochi-gaming-mode.sh' "$ENSURE" || fail "ensure-kimochi.sh must wrap via kimochi-gaming-mode.sh"
grep -q 'KIMOCHI_GAMING_MODE_ROOT' "$ENSURE" || fail "ensure-kimochi.sh must honor KIMOCHI_GAMING_MODE_ROOT"

tmp="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '$tmp'" EXIT
mkdir -p "$tmp/current/scripts"
printf '#!/bin/sh\necho vendor\n' >"$tmp/current/scripts/launch-from-steam.sh"
touch "$tmp/current/Kimochi.AppImage"
printf '#!/bin/sh\necho vendor-launch\n' >"$tmp/launch.sh"

KIMOCHI_GAMING_MODE_ROOT="$tmp" KIMOCHI_APPIMAGE="$tmp/current/Kimochi.AppImage" \
  "$ENSURE" >/tmp/ensure-kimochi-test.out
grep -q 'steamos-playbook kimochi-gaming-mode wrap' "$tmp/launch.sh" \
  || fail "ensure-kimochi.sh must stamp launch.sh"
grep -F -q "$LAUNCHER" "$tmp/launch.sh" || fail "wrap must exec $LAUNCHER"

echo "test_kimochi_gaming_mode ok"
