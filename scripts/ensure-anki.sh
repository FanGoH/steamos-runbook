#!/usr/bin/env bash
# Ensure Anki (user Flatpak) and the AnkiConnect add-on.
# Uses /home, so it fits SteamOS's tiny root partition. Do not pacman anki.
#
# AnkiConnect serves http://127.0.0.1:8765 only while Anki is running.
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
data.setdefault("disabled", False)
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
  if pgrep -x anki >/dev/null 2>&1; then
    echo "Anki is running; restart it to load AnkiConnect."
  else
    echo "Start Anki (Desktop) so AnkiConnect can listen on 127.0.0.1:8765."
  fi
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

exit 0
