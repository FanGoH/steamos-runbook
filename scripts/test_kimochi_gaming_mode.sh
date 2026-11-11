#!/usr/bin/env bash
# Offline checks for the Kimochi Game Mode overlay sidecar (no GUI start).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "FAIL: $*" >&2; exit 1; }

LAUNCHER="$ROOT/scripts/kimochi-gaming-mode.sh"
OVERLAY="$ROOT/scripts/kimochi-overlay.sh"
ENSURE="$ROOT/scripts/ensure-kimochi.sh"
PATCHER="$ROOT/scripts/patch-kimochi-controller-nav.py"

[ -x "$LAUNCHER" ] || fail "kimochi-gaming-mode.sh not executable"
[ -x "$OVERLAY" ] || fail "kimochi-overlay.sh not executable"
[ -x "$ENSURE" ] || fail "ensure-kimochi.sh not executable"
[ -f "$PATCHER" ] || fail "patch-kimochi-controller-nav.py missing"

grep -q 'PATH="/usr/bin:/bin:' "$LAUNCHER" "$OVERLAY" || fail "scripts must prepend /usr/bin:/bin"
grep -q 'FUSERMOUNT_PROG' "$OVERLAY" || fail "overlay must set FUSERMOUNT_PROG"
grep -q 'launch-gaming-mode.sh' "$OVERLAY" || fail "overlay must exec Kimochi's launch-gaming-mode.sh"
grep -q 'launch-from-steam.sh' "$OVERLAY" && fail "overlay must not use launch-from-steam.sh (that sets MANAGED=1)"
grep -q 'patch-kimochi-controller-nav.py' "$OVERLAY" || fail "overlay must run controller-nav patcher"
grep -q 'extracted/AppRun' "$OVERLAY" || fail "overlay must exec patched AppDir AppRun"
grep -q -- '--elf' "$OVERLAY" || fail "overlay must patch the on-disk ELF"
grep -q -- '--prefer-pad' "$OVERLAY" || fail "overlay must pin the Sunshine/Steam pad"
grep -q 'unset SteamAppId' "$OVERLAY" || fail "overlay must unset SteamAppId so Kimochi is not a Steam game"
grep -q 'release_steam' "$OVERLAY" || fail "overlay must SIGCONT steam so Guide/QAM stay alive"
grep -q 'kimochi-input' "$OVERLAY" || fail "overlay must drop the idle steam-input watchdog"
grep -q 'unset LD_PRELOAD' "$OVERLAY" || fail "overlay must unset Steam LD_PRELOAD"
if grep -q 'KIMOCHI_STEAM_MANAGED=1' "$OVERLAY" "$LAUNCHER"; then
  fail "must not set KIMOCHI_STEAM_MANAGED=1 (that steals HDMI and SIGSTOPs steam)"
fi
if grep -qE 'xprop .*GAMESCOPE_FOCUSED_APP|GAMESCOPECTRL_BASELAYER_APPID' "$OVERLAY" "$LAUNCHER"; then
  fail "must not write gamescope focus atoms (that killed the Steam menu)"
fi
grep -q 'steamos-kimochi-overlay.service' "$LAUNCHER" || fail "Steam tile must kick the overlay unit and exit"
grep -q 'systemctl --user restart' "$LAUNCHER" || fail "Steam tile must restart the overlay unit"
grep -q 'pgrep -x kimochi' "$LAUNCHER" "$OVERLAY" || fail "must use pgrep -x kimochi"
grep -q 'xor eax,eax' "$PATCHER" || fail "patcher must document xor eax,eax"
grep -q '0fb6057bc59b01' "$PATCHER" || fail "patcher must pin Kimochi 0.8.1 opcode bytes"
if grep -qE 'pgrep -f|pkill -f' "$LAUNCHER" "$OVERLAY" "$ENSURE" "$PATCHER"; then
  fail "must not pgrep -f / pkill -f"
fi
grep -q 'shortcuts.vdf' "$ENSURE" || fail "ensure-kimochi.sh must document no shortcuts.vdf rewrite"
grep -q 'kimochi-gaming-mode.sh' "$ENSURE" || fail "ensure-kimochi.sh must wrap via kimochi-gaming-mode.sh"
grep -q 'kimochi-overlay.sh' "$ENSURE" || fail "ensure-kimochi.sh must install kimochi-overlay.sh"
grep -q 'KIMOCHI_GAMING_MODE_ROOT' "$ENSURE" || fail "ensure-kimochi.sh must honor KIMOCHI_GAMING_MODE_ROOT"
if grep -qE 'WantedBy=gamescope-session.target' "$ENSURE"; then
  fail "overlay must not auto-start with Game Mode (that SIGSTOPs steam)"
fi
grep -q 'ExecStopPost' "$ENSURE" || fail "overlay unit must SIGCONT steam on stop"
grep -q 'kimochi-cont-steam.sh' "$ENSURE" "$OVERLAY" || fail "overlay must resume steam via kimochi-cont-steam.sh"
grep -q 'PartOf=gamescope-session.service' "$ENSURE" || fail "overlay unit must stop with Game Mode"
grep -q 'UnsetEnvironment=SteamAppId' "$ENSURE" || fail "overlay unit must drop SteamAppId"

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
grep -q 'placeholder; skip overlay unit' /tmp/ensure-kimochi-test.out \
  || fail "placeholder AppImage must skip the overlay unit"

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
assert mod.prefer_stream_pad_index(["EmuPads P1", "Microsoft X-Box 360 pad 0"]) == 1
assert mod.prefer_stream_pad_index(
    ["EmuPads P1", "Sunshine (libvirtualhid) Odin2_Portal", "Microsoft X-Box 360 pad 0"]
) == 1
print("patcher --elf ok")
PY

echo "test_kimochi_gaming_mode ok"
