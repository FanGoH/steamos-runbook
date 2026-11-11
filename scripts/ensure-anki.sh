#!/usr/bin/env bash
# Ensure Anki (user Flatpak), the AnkiConnect add-on, and a headless user
# service so the API stays up in Plasma and Game Mode.
# Uses /home, so it fits SteamOS's tiny root partition. Do not pacman anki.
#
# AnkiConnect listens on 127.0.0.1:${ANKICONNECT_PORT:-18765} (8765 is
# Decky Clipboard). Desktop window: scripts/anki-gui.sh
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
if ! require_playbook_user; then
  exit 2
fi

FLATPAK_ID="${ANKI_FLATPAK_ID:-net.ankiweb.Anki}"
REMOTE="${FLATPAK_REMOTE:-flathub}"
ADDON_ID="${ANKICONNECT_ADDON_ID:-2055492159}"
VERSION="${ANKICONNECT_VERSION:-26.10.14.0}"
URL="${ANKICONNECT_URL:-https://git.sr.ht/~foosoft/anki-connect/archive/${VERSION}.tar.gz}"
ADDONS_DIR="${ANKI_ADDONS_DIR:-/home/${STEAMOS_USER}/.var/app/${FLATPAK_ID}/data/Anki2/addons21}"
DEST="${ADDONS_DIR}/${ADDON_ID}"
STAMP="${DEST}/.playbook-ankiconnect-version"
SERVICE="${ANKI_CONNECT_SERVICE:-anki-connect.service}"
UNIT_PATH="/home/${STEAMOS_USER}/.config/systemd/user/${SERVICE}"
DAEMON="$ROOT/scripts/anki-connect-daemon.sh"
PORT="${ANKICONNECT_PORT:-18765}"
PROFILE="${ANKI_PROFILE:-User 1}"
LOG="$ROOT/logs/anki-connect.log"
UID_NUM="$(id -u "$STEAMOS_USER")"

flatpak_installed() {
  flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1 \
    || flatpak info "$FLATPAK_ID" >/dev/null 2>&1
}

ensure_flathub() {
  if flatpak remotes --user 2>/dev/null | awk '{print $1}' | grep -Fxq "$REMOTE"; then
    return 0
  fi
  if flatpak remotes 2>/dev/null | awk '{print $1}' | grep -Fxq "$REMOTE"; then
    return 0
  fi
  echo "Adding Flatpak remote: $REMOTE"
  flatpak remote-add --user --if-not-exists "$REMOTE" "https://dl.flathub.org/repo/flathub.flatpakrepo"
}

install_anki() {
  if flatpak_installed; then
    echo "Anki already installed ($FLATPAK_ID)."
    if flatpak info --user "$FLATPAK_ID" >/dev/null 2>&1; then
      flatpak info --user "$FLATPAK_ID" | grep -E 'ID:|Version:|Installation:' || true
    else
      flatpak info "$FLATPAK_ID" 2>/dev/null | grep -E 'ID:|Version:|Installation:' || true
    fi
    return 0
  fi
  if ! command -v flatpak >/dev/null 2>&1; then
    echo "flatpak not installed."
    record_manual "Install flatpak, then Anki" <<EOF
flatpak install --user $REMOTE $FLATPAK_ID
EOF
    return 1
  fi
  ensure_flathub || true
  echo "Installing Anki ($FLATPAK_ID) as user Flatpak..."
  if flatpak install --user -y "$REMOTE" "$FLATPAK_ID"; then
    echo "Anki installed."
    return 0
  fi
  echo "Anki install failed."
  record_manual "Install Anki Flatpak" <<EOF
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub $FLATPAK_ID
EOF
  return 1
}

write_meta() {
  python3 - "$DEST" <<'PY'
import json, sys, time
from pathlib import Path
dest = Path(sys.argv[1])
path = dest / "meta.json"
data = {}
if path.is_file():
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        data = {}
if not isinstance(data, dict):
    data = {}
data.setdefault("name", "Anki-Connect")
data["disabled"] = False
# 0 = no cap. A stale 260800 cap hides the add-on on Anki 26.09.
data["max_point_version"] = 0
data.setdefault("mod", int(time.time()))
path.write_text(json.dumps(data, indent=2) + "\n")
PY
}

plugin_src_from_extract() {
  local root="$1"
  local d
  while IFS= read -r d; do
    if [ -f "$d/__init__.py" ]; then
      printf '%s\n' "$d"
      return 0
    fi
  done < <(find "$root" -type d -name plugin 2>/dev/null)
  return 1
}

install_ankiconnect() {
  local have_init=0
  local have_stamp=""
  [ -f "$DEST/__init__.py" ] && have_init=1
  [ -f "$STAMP" ] && have_stamp="$(tr -d '[:space:]' <"$STAMP" || true)"

  if [ "$have_init" -eq 1 ] && [ "$have_stamp" = "$VERSION" ]; then
    echo "AnkiConnect $VERSION already installed ($DEST)."
    return 0
  fi
  if [ "$have_init" -eq 1 ] && [ -z "$have_stamp" ]; then
    echo "AnkiConnect already present (not playbook-stamped); leaving $DEST."
    return 0
  fi

  local tmp src saved_config=""
  tmp="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '$tmp'" RETURN
  echo "Downloading AnkiConnect ${VERSION}..."
  if ! curl -fsSL --max-time 60 -o "$tmp/anki-connect.tar.gz" "$URL"; then
    echo "AnkiConnect download failed: $URL"
    record_manual "Install AnkiConnect add-on 2055492159" <<EOF
# In Anki: Tools → Add-ons → Get Add-ons → 2055492159
# Or: $ROOT/scripts/ensure-anki.sh
EOF
    return 1
  fi
  tar -xzf "$tmp/anki-connect.tar.gz" -C "$tmp"
  src="$(plugin_src_from_extract "$tmp" || true)"
  if [ -z "$src" ] || [ ! -f "$src/__init__.py" ]; then
    echo "AnkiConnect archive missing plugin/__init__.py"
    return 1
  fi
  mkdir -p "$DEST"
  if [ -f "$DEST/config.json" ]; then
    saved_config="$tmp/saved-config.json"
    cp -a "$DEST/config.json" "$saved_config"
  fi
  cp -a "$src"/. "$DEST/"
  if [ -n "$saved_config" ]; then
    cp -a "$saved_config" "$DEST/config.json"
  fi
  write_meta
  printf '%s\n' "$VERSION" >"$STAMP"
  echo "AnkiConnect $VERSION installed in $DEST"
}

merge_ankiconnect_config() {
  local cfg="$DEST/config.json"
  mkdir -p "$DEST"
  python3 - "$cfg" "$PORT" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
port = int(sys.argv[2])
data = {}
if path.is_file():
    try:
        data = json.loads(path.read_text() or "{}")
    except (OSError, json.JSONDecodeError):
        data = {}
if not isinstance(data, dict):
    data = {}
data.setdefault("apiKey", None)
data.setdefault("apiLogPath", None)
data["webBindAddress"] = "127.0.0.1"
data["webBindPort"] = port
cors = list(data.get("webCorsOriginList") or [])
if "*" not in cors:
    cors.append("*")
data["webCorsOriginList"] = cors
ignore = list(data.get("ignoreOriginList") or [])
if "*" not in ignore:
    ignore.append("*")
data["ignoreOriginList"] = ignore
path.write_text(json.dumps(data, indent=4) + "\n")
PY
  write_meta
  echo "AnkiConnect config: 127.0.0.1:${PORT} (8765 is Decky Clipboard)."
}

anki_connect_up() {
  local out
  out="$(curl -sS --max-time 2 -H 'Content-Type: application/json' \
    --data '{"action":"version","version":6}' \
    "http://127.0.0.1:${PORT}/" 2>/dev/null || true)"
  printf '%s' "$out" | grep -q '"result"' && return 0
  out="$(curl -sS --max-time 2 -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":1,"method":"api.describe","params":{}}' \
    "http://127.0.0.1:${PORT}/api/v1" 2>/dev/null || true)"
  printf '%s' "$out" | grep -qE '"result"|"jsonrpc"' && return 0
  return 1
}

install_anki_connect_service() {
  if [ ! -x "$DAEMON" ]; then
    chmod +x "$DAEMON" "$ROOT/scripts/anki-gui.sh" 2>/dev/null || true
  fi
  if [ ! -x "$DAEMON" ]; then
    echo "Missing $DAEMON"
    return 1
  fi
  mkdir -p "/home/${STEAMOS_USER}/.config/systemd/user" "$ROOT/logs"

  local profile_dir="/home/${STEAMOS_USER}/.var/app/${FLATPAK_ID}/data/Anki2/${PROFILE}"
  if [ ! -d "$profile_dir" ]; then
    echo "Anki profile '$PROFILE' is missing; open Anki once on Desktop first."
    record_manual "Create Anki profile, then start AnkiConnect" <<EOF
flatpak run --user $FLATPAK_ID
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
$ROOT/scripts/ensure-anki.sh
EOF
    return 2
  fi

  local desired_unit
  desired_unit="$(cat <<EOS
[Unit]
Description=AnkiConnect (headless Anki)
Documentation=file://$ROOT/scripts/ensure-anki.sh
After=default.target
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
ExecStart=$DAEMON
ExecStop=/usr/bin/flatpak kill $FLATPAK_ID
Restart=always
RestartSec=5
TimeoutStopSec=30
Environment=HOME=/home/$STEAMOS_USER
Environment=USER=$STEAMOS_USER
Environment=XDG_RUNTIME_DIR=/run/user/$UID_NUM
Environment=DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$UID_NUM/bus
Environment=ANKI_FLATPAK_ID=$FLATPAK_ID
UnsetEnvironment=DISPLAY WAYLAND_DISPLAY
StandardOutput=append:$LOG
StandardError=append:$LOG

[Install]
WantedBy=default.target
WantedBy=gamescope-session.target
EOS
)"

  local unit_changed=0
  if [ ! -f "$UNIT_PATH" ] || [ "$(cat "$UNIT_PATH")" != "$desired_unit" ]; then
    printf '%s\n' "$desired_unit" >"$UNIT_PATH"
    systemctl --user daemon-reload
    unit_changed=1
    echo "Updated $SERVICE unit."
  fi

  if ! systemctl --user is-enabled "$SERVICE" >/dev/null 2>&1; then
    systemctl --user enable "$SERVICE"
    echo "Enabled $SERVICE."
  else
    echo "$SERVICE already enabled."
  fi

  if [ "$(loginctl show-user "$STEAMOS_USER" -p Linger --value 2>/dev/null || true)" != "yes" ]; then
    if loginctl enable-linger "$STEAMOS_USER" 2>/dev/null; then
      echo "Enabled linger for $STEAMOS_USER."
    else
      record_manual "Enable linger so AnkiConnect survives logout / Game Mode" <<EOF
loginctl enable-linger $STEAMOS_USER
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user restart $SERVICE
EOF
    fi
  fi

  local need_start=0
  if [ "$unit_changed" -eq 1 ]; then
    need_start=1
  elif ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
    need_start=1
  elif ! anki_connect_up; then
    need_start=1
  fi

  if [ "$need_start" -eq 1 ]; then
    if pgrep -x anki >/dev/null 2>&1 && ! systemctl --user is-active "$SERVICE" >/dev/null 2>&1; then
      echo "Stopping Desktop Anki so $SERVICE can own the collection."
      /usr/bin/flatpak kill "$FLATPAK_ID" >/dev/null 2>&1 || true
      sleep 1
    fi
    systemctl --user restart "$SERVICE" || systemctl --user start "$SERVICE"
    echo "Started $SERVICE."
  else
    echo "$SERVICE already active."
  fi

  local i=0
  while [ "$i" -lt 45 ]; do
    if anki_connect_up; then
      echo "AnkiConnect answering http://127.0.0.1:${PORT}/ (legacy version 6)."
      echo "Desktop window: $ROOT/scripts/anki-gui.sh (stops the daemon, then starts it again)."
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done

  echo "AnkiConnect did not answer http://127.0.0.1:${PORT}/"
  echo "See $LOG and: journalctl --user -u $SERVICE -n 40 --no-pager"
  record_manual "Start AnkiConnect daemon" <<EOF
export XDG_RUNTIME_DIR=/run/user/\$(id -u)
systemctl --user status $SERVICE --no-pager
journalctl --user -u $SERVICE -n 40 --no-pager
tail -40 $LOG
EOF
  return 1
}

if ! install_anki; then
  exit 1
fi

# Host network so AnkiConnect's 127.0.0.1:8765 is reachable outside the sandbox.
# Flathub already ships --share=network; this keeps a user override if it was dropped.
if command -v flatpak >/dev/null 2>&1 && flatpak_installed; then
  flatpak override --user --share=network "$FLATPAK_ID" >/dev/null 2>&1 || true
fi

if ! install_ankiconnect; then
  exit 1
fi

if ! merge_ankiconnect_config; then
  exit 1
fi

if ! install_anki_connect_service; then
  exit 1
fi

exit 0
