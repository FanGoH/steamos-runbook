#!/usr/bin/env bash
# Offline checks for the Kimochi Game Mode AppImage wrap (no GUI start).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

LAUNCHER="$ROOT/scripts/kimochi-gaming-mode.sh"
ENSURE="$ROOT/scripts/ensure-kimochi.sh"
PATCHER="$ROOT/scripts/patch-kimochi-controller-nav.py"

[ -x "$LAUNCHER" ] || fail "kimochi-gaming-mode.sh not executable"
[ -x "$ENSURE" ] || fail "ensure-kimochi.sh not executable"
[ -f "$PATCHER" ] || fail "patch-kimochi-controller-nav.py missing"

grep -q 'PATH="/usr/bin:/bin:' "$LAUNCHER" || fail "launcher must prepend /usr/bin:/bin"
grep -q 'FUSERMOUNT_PROG' "$LAUNCHER" || fail "launcher must set FUSERMOUNT_PROG"
grep -q 'launch-from-steam.sh' "$LAUNCHER" || fail "launcher must exec Kimochi's launch-from-steam.sh"
grep -q 'patch-kimochi-controller-nav.py' "$LAUNCHER" || fail "launcher must run controller-nav patcher"
grep -q 'extracted/AppRun' "$LAUNCHER" || fail "launcher must exec patched AppDir AppRun"
grep -q -- '--elf' "$LAUNCHER" || fail "launcher must patch the on-disk ELF"
grep -q 'xor eax,eax' "$PATCHER" || fail "patcher must document xor eax,eax"
grep -q '0fb6057bc59b01' "$PATCHER" || fail "patcher must pin Kimochi 0.8.1 opcode bytes"
if grep -qE 'pgrep -f|pkill -f' "$LAUNCHER" "$ENSURE" "$PATCHER"; then
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

fake="$(mktemp)"
# shellcheck disable=SC2064
trap "rm -rf '$tmp' '$fake'" EXIT
python3 - "$PATCHER" "$fake" <<'PY'
from pathlib import Path
import importlib.util
import subprocess
import sys

patcher, fake = sys.argv[1], sys.argv[2]
spec = importlib.util.spec_from_file_location("patch_kimochi", patcher)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
Path(fake).write_bytes(b"HDR" + mod.NEEDLE + b"END")
rc = subprocess.call(["python3", patcher, "--elf", fake])
out = Path(fake).read_bytes()
assert rc == 0, rc
assert out.find(mod.PATCHED) == 3 + mod.PATCH_AT
print("patcher --elf ok")
PY

echo "test_kimochi_gaming_mode ok"
