#!/usr/bin/env bash
# Detect the Game Mode kms setcap sudoers drop-in. Do not write /etc (needs
# password + steamos-readonly). SteamOS updates wipe /etc/sudoers.d.
# Dest must be zzz-* so it sorts after wheel (last matching tag wins).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

SETCAP_BIN="${SUNSHINE_DS_KMS_SETCAP_BIN:-/usr/bin/setcap}"
KMS_BIN="${SUNSHINE_DS_KMS_BIN:-/home/${STEAMOS_USER:-deck}/.local/bin/sunshine-ds-kms}"
SRC="$ROOT/sudoers/zzz-sunshine-ds-kms-setcap"
DEST="/etc/sudoers.d/zzz-sunshine-ds-kms-setcap"
OLD_DEST="/etc/sudoers.d/sunshine-ds-kms-setcap"

kms_setcap_nopasswd() {
  [ -x "$SETCAP_BIN" ] && [ -e "$KMS_BIN" ] &&
    sudo -n "$SETCAP_BIN" cap_sys_admin+ep "$KMS_BIN" >/dev/null 2>&1
}

ask_install() {
  record_manual "install zzz-sunshine-ds-kms-setcap (after wheel)" <<EOF
# Last sudoers match wins. sunshine-ds-kms-setcap sorts before wheel, so
# NOPASSWD is ignored. zzz- sorts last. Filename must not contain a dot.
# SteamOS root is readonly; a SteamOS update can wipe this drop-in.
sudo steamos-readonly disable
sudo rm -f $OLD_DEST
sudo install -m 440 $SRC $DEST
sudo visudo -cf $DEST
sudo steamos-readonly enable
sudo -n $SETCAP_BIN cap_sys_admin+ep $KMS_BIN
getcap $KMS_BIN
# Never setcap ~/.local/bin/sunshine-ds (desktop Distrobox path).
EOF
}

if [ ! -f "$SRC" ]; then
  echo "Missing playbook fragment $SRC"
  exit 1
fi

if kms_setcap_nopasswd; then
  echo "sudo -n setcap works for $KMS_BIN ($(getcap "$KMS_BIN" 2>/dev/null || echo cap ok))"
  if [ -e "$OLD_DEST" ]; then
    echo "note: leftover $OLD_DEST is unused (wheel overrides it). Safe to remove on the next install."
  fi
  exit 0
fi

echo "sudo -n $SETCAP_BIN is not allowed for $KMS_BIN."
if [ -e "$OLD_DEST" ] && [ ! -e "$DEST" ]; then
  echo "Found $OLD_DEST; it sorts before wheel so NOPASSWD does not apply."
fi
ask_install
exit 2
