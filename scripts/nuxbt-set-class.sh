#!/usr/bin/env bash
# Set Bluetooth Class of Device to Nintendo Pro Controller (0x002508).
# Required on De-FanGoH: Distrobox cannot raw-HCI set_class (PermissionError),
# so NXBT leaves Class at 0x400000 and Switch 2 ignores the advertiser.
# Phone still sees the "Pro Controller" name — CoD is what Switch cares about.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Re-run with sudo: sudo $0"
  exit 1
fi

hciconfig hci0 class 0x002508
echo "hciconfig: $(hciconfig hci0 | awk -F'Class: ' '/Class:/{print $2; exit}')"
bluetoothctl show | awk '/Class:/{print "bluetoothctl:", $0; exit}'
