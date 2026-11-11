#!/usr/bin/env bash
# Offline checks: Kimochi Game Mode uses vendor launch.sh, not a playbook wrap.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

ENSURE="$ROOT/scripts/ensure-kimochi.sh"
[ -x "$ENSURE" ] || fail "ensure-kimochi.sh not executable"

[ ! -e "$ROOT/scripts/kimochi-gaming-mode.sh" ] || fail "kimochi-gaming-mode.sh wrap must be gone"
[ ! -e "$ROOT/scripts/kimochi-overlay.sh" ] || fail "kimochi-overlay.sh must be gone"
[ ! -e "$ROOT/scripts/kimochi-cont-steam.sh" ] || fail "kimochi-cont-steam.sh must be gone"
[ ! -e "$ROOT/scripts/patch-kimochi-controller-nav.py" ] || fail "controller-nav patcher must be gone"

grep -q 'shortcuts.vdf' "$ENSURE" || fail "ensure-kimochi.sh must document no shortcuts.vdf rewrite"
grep -q 'KIMOCHI_GAMING_MODE_ROOT' "$ENSURE" || fail "ensure-kimochi.sh must honor KIMOCHI_GAMING_MODE_ROOT"
grep -q 'launch-from-steam.sh' "$ENSURE" || fail "ensure must restore vendor launch-from-steam.sh"
if grep -q "exec /bin/sh .*kimochi-gaming-mode.sh" "$ENSURE"; then
  fail "ensure must not wrap via kimochi-gaming-mode.sh"
fi
if grep -q 'steamos-playbook kimochi-gaming-mode wrap' "$ENSURE"; then
  # Allowed only as the leftover stamp to detect and remove.
  grep -q 'WRAP_MARK=' "$ENSURE" || fail "wrap mark must only be the leftover detector"
fi
if grep -qE 'pgrep -f|pkill -f' "$ENSURE"; then
  fail "must not pgrep -f / pkill -f"
fi

tmp="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '$tmp'" EXIT
mkdir -p "$tmp/current/scripts"
printf '#!/bin/sh\necho vendor\n' >"$tmp/current/scripts/launch-from-steam.sh"
touch "$tmp/current/Kimochi.AppImage"
printf '%s\n' '#!/bin/sh' '# steamos-playbook kimochi-gaming-mode wrap' \
  'exec /bin/sh /tmp/kimochi-gaming-mode.sh "$@"' >"$tmp/launch.sh"

KIMOCHI_GAMING_MODE_ROOT="$tmp" KIMOCHI_APPIMAGE="$tmp/current/Kimochi.AppImage" \
  "$ENSURE" >/tmp/ensure-kimochi-test.out
grep -q 'steamos-playbook kimochi-gaming-mode wrap' "$tmp/launch.sh" \
  && fail "ensure-kimochi.sh must unwrap launch.sh"
grep -q 'launch-from-steam.sh' "$tmp/launch.sh" \
  || fail "restored launch.sh must exec vendor launch-from-steam.sh"
grep -F -q "$tmp/current/Kimochi.AppImage" "$tmp/launch.sh" \
  || fail "restored launch.sh must exec the AppImage"

echo "test_kimochi_gaming_mode ok"
