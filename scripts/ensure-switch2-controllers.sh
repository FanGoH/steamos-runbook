#!/usr/bin/env bash
# Install / restore the Switch 2 BLE → uinput bridge (user-space, home-dir venv).
# SteamOS updates can drop user units; pairing is never automated.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

DIR="${SWITCH2_CONTROLLERS_DIR:-/home/${STEAMOS_USER}/code/switch2-controllers-linux}"
REPO_URL="${SWITCH2_CONTROLLERS_REPO:-https://github.com/trevlars/switch2-controllers-linux.git}"

mkdir -p "$(dirname "$DIR")"

if [ ! -d "$DIR/.git" ] && [ ! -f "$DIR/scripts/install.sh" ]; then
  echo "Cloning Switch 2 controllers into $DIR"
  if ! git clone "$REPO_URL" "$DIR"; then
    echo "git clone failed."
    record_manual "Clone switch2-controllers-linux" <<EOF
mkdir -p $(dirname "$DIR")
git clone $REPO_URL $DIR
$ROOT/scripts/ensure-switch2-controllers.sh
EOF
    exit 1
  fi
fi

if [ ! -x "$DIR/scripts/install.sh" ]; then
  echo "install.sh missing in $DIR"
  record_manual "Checkout switch2-controllers-linux" <<EOF
git clone $REPO_URL $DIR
EOF
  exit 1
fi

echo "Switch 2 controllers checkout: $DIR"
chmod +x "$DIR/scripts/"*.sh "$DIR/scripts/"*.py "$DIR/system/"*.sh 2>/dev/null || true

# Home-dir venv + user units. Skips Bazzite Eden reorder on Steam OS.
if ! bash "$DIR/scripts/install.sh"; then
  echo "install.sh failed."
  record_manual "Install Switch 2 controller bridge" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
cd $DIR
bash scripts/install.sh
EOF
  exit 1
fi

# Decky plugins dir is root-owned on this box.
PLUGIN_DEST="${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/plugins/Switch2Controllers"
if [ -d "$(dirname "$PLUGIN_DEST")" ] && [ ! -f "$PLUGIN_DEST/main.py" ]; then
  if sudo -n true 2>/dev/null; then
    sudo bash "$DIR/scripts/install-decky.sh" --install-only \
      "${DECKY_HOMEBREW_DIR:-/home/$STEAMOS_USER/homebrew}/plugins"
    echo "Installed Decky plugin to $PLUGIN_DEST"
  else
    echo "Decky plugin not installed (plugins dir is not writable)."
    record_manual "Install Switch 2 Controllers Decky plugin" <<EOF
sudo bash $DIR/scripts/install-decky.sh --install-only $HOME/homebrew/plugins
# Or Decky → Settings → Developer → Install plugin from zip:
#   $DIR/decky/Switch2Controllers.zip
EOF
  fi
elif [ -f "$PLUGIN_DEST/main.py" ]; then
  echo "Decky plugin already present ($PLUGIN_DEST)"
fi

CFG="/home/$STEAMOS_USER/.config/nso-gc/config.json"
paired=0
if [ -f "$CFG" ]; then
  paired="$(python3 - "$CFG" <<'PY' 2>/dev/null || echo 0
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
print(len(data.get("controllers") or []))
PY
)"
fi
if [ "${paired:-0}" -eq 0 ]; then
  echo "No paired Switch 2 controllers yet."
  record_manual "Pair each Switch 2 controller once (hold Sync)" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
cd $DIR
$DIR/.venv/bin/python -m ngc pair || $DIR/.venv312/bin/python -m ngc pair
# Repeat for a second pad. Then: systemctl --user status nso-gc.service
EOF
  exit 2
fi

echo "nso-gc.service: $(systemctl --user is-active nso-gc.service 2>/dev/null || echo inactive)"
exit 0
