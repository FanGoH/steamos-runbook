#!/usr/bin/env bash
# Detect the pad-hide sysfs sudoers drop-in (SSH). Decky PluginLoader is
# already root and does not need this. Do not write /etc (needs password +
# steamos-readonly). SteamOS updates wipe /etc/sudoers.d and udev.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

HELPER="$ROOT/scripts/hide-controllers-sysfs.sh"
SRC="$ROOT/sudoers/zzz-hide-controllers"
DEST="/etc/sudoers.d/zzz-hide-controllers"
UDEV_SRC="$ROOT/udev/99-hide-controllers.rules"
UDEV_DEST="/etc/udev/rules.d/99-hide-controllers.rules"

if [ ! -x "$HELPER" ]; then
  echo "Missing $HELPER"
  exit 1
fi

if ! python3 "$ROOT/scripts/hide-controllers.py" self-test >/dev/null; then
  echo "hide-controllers self-test failed."
  exit 1
fi

helper_nopasswd() {
  sudo -n "$HELPER" >/dev/null 2>&1
  rc=$?
  # usage error (2) still means sudo accepted the binary
  [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]
}

ask_install() {
  record_manual "install zzz-hide-controllers (after wheel) + udev" <<EOF
# Last sudoers match wins. zzz- sorts after wheel. Filename must not contain a dot.
# SteamOS root is readonly; a SteamOS update can wipe this drop-in.
sudo steamos-readonly disable
sudo install -m 440 $SRC $DEST
sudo visudo -cf $DEST
sudo install -m 644 $UDEV_SRC $UDEV_DEST
sudo udevadm control --reload
sudo steamos-readonly enable
sudo -n $HELPER
# Decky QAM does not need this (PluginLoader is root). SSH hide/show does.
EOF
}

if helper_nopasswd; then
  echo "sudo -n $HELPER works (SSH hide/show)."
  if [ ! -f "$UDEV_DEST" ]; then
    echo "udev $UDEV_DEST is missing; replug will not re-hide until status/apply."
    ask_install
    exit 2
  fi
  exit 0
fi

echo "sudo -n $HELPER is not allowed (SSH hide needs the sudoers drop-in)."
ask_install
exit 2
