#!/usr/bin/env bash
# Steam QAM performance overlay (mangoapp) preset 2. Stock horizontal
# stretch paints a 1920-wide HUD on the 1080p overlay window, which
# 1/4-flashes on 4K HDMI. Keep the bar/graphs; drop stretch and alpha.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

SRC="$ROOT/mangohud/presets.conf"
DEST="/home/$STEAMOS_USER/.config/MangoHud/presets.conf"
DROP_DIR="/home/$STEAMOS_USER/.config/systemd/user/gamescope-mangoapp.service.d"
DROP="$DROP_DIR/playbook-presets.conf"

if [ ! -f "$SRC" ]; then
  echo "Missing $SRC"
  exit 1
fi

mkdir -p "$(dirname "$DEST")" "$DROP_DIR"

changed=0
if [ ! -f "$DEST" ] || ! cmp -s "$SRC" "$DEST"; then
  cp "$SRC" "$DEST"
  changed=1
  echo "Installed $DEST"
else
  echo "MangoHud presets already current ($DEST)"
fi

drop_tmp="$(mktemp)"
cat >"$drop_tmp" <<EOF
# Playbook: mangoapp reads this presets.conf (QAM slider still
# writes preset= / no_display in the gamescope mangohud.config).
[Service]
Environment=MANGOHUD_PRESETSFILE=$DEST
EOF

if [ ! -f "$DROP" ] || ! cmp -s "$drop_tmp" "$DROP"; then
  mv "$drop_tmp" "$DROP"
  changed=1
  echo "Updated $DROP"
  systemctl --user daemon-reload
else
  rm -f "$drop_tmp"
  echo "mangoapp presets drop-in already current."
fi

if ! systemctl --user is-active gamescope-mangoapp.service >/dev/null 2>&1; then
  echo "gamescope-mangoapp.service not active (ok on Plasma)."
  exit 0
fi

if [ "$changed" -eq 1 ]; then
  systemctl --user restart gamescope-mangoapp.service
  echo "Restarted gamescope-mangoapp.service"
fi

exit 0
