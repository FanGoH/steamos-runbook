#!/usr/bin/env bash
# Update Decky Tender (romm-tender) from the official GitHub zip, then put
# the playbook rom-launcher wrap back. Tender releases overwrite bin/rom-launcher.
#
#   scripts/ensure-tender.sh           # update if behind, then wrap
#   scripts/ensure-tender.sh --status  # installed vs latest, no download
#   scripts/ensure-tender.sh --wrap    # wrap only
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

TENDER_REPO="${TENDER_REPO:-danielcopper/romm-tender}"
TENDER_PLUGIN_DIR="${TENDER_PLUGIN_DIR:-/home/${STEAMOS_USER}/homebrew/plugins/romm-tender}"
TENDER_PLUGIN_NAME="${TENDER_PLUGIN_NAME:-Tender}"
DO_STATUS=0
DO_WRAP=0
for arg in "$@"; do
  case "$arg" in
    --status) DO_STATUS=1 ;;
    --wrap) DO_WRAP=1 ;;
    -h|--help)
      sed -n '2,9p' "$0"
      exit 0
      ;;
    *)
      echo "usage: $0 [--status] [--wrap]" >&2
      exit 2
      ;;
  esac
done

installed_version() {
  local json="$TENDER_PLUGIN_DIR/plugin.json"
  if [ ! -f "$json" ]; then
    echo ""
    return 1
  fi
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version") or "")' "$json" 2>/dev/null
}

version_lt() {
  python3 - "$1" "$2" <<'PY'
import sys
def parts(s):
    s = (s or "").strip().lower()
    for prefix in ("tender-v", "tender-", "v"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    out = []
    for bit in s.replace("-", ".").split("."):
        if bit.isdigit():
            out.append(int(bit))
    return tuple(out or (0,))
sys.exit(0 if parts(sys.argv[1]) < parts(sys.argv[2]) else 1)
PY
}

latest_release() {
  local api url tag zip
  if [ -n "${TENDER_ZIP_URL:-}" ]; then
    printf '%s %s\n' "${TENDER_RELEASE_TAG:-pinned}" "$TENDER_ZIP_URL"
    return 0
  fi
  if [ -n "${TENDER_RELEASE_TAG:-}" ]; then
    api="https://api.github.com/repos/${TENDER_REPO}/releases/tags/${TENDER_RELEASE_TAG}"
  else
    api="https://api.github.com/repos/${TENDER_REPO}/releases/latest"
  fi
  url="$(curl -sS --max-time 20 -H 'Accept: application/vnd.github+json' "$api" 2>/dev/null || true)"
  if [ -z "$url" ]; then
    return 1
  fi
  python3 -c '
import json, sys
data = json.loads(sys.argv[1])
tag = data.get("tag_name") or ""
assets = data.get("assets") or []
prefer = ("Tender.zip", "tender.zip")
zip_url = ""
for name in prefer:
    for asset in assets:
        if asset.get("name") == name:
            zip_url = asset.get("browser_download_url") or ""
            break
    if zip_url:
        break
if not zip_url and assets:
    zip_url = assets[0].get("browser_download_url") or ""
if not zip_url:
    sys.exit(1)
print(tag, zip_url)
' "$url"
}

install_tree() {
  local src="$1" dest="$2"
  if [ -w "$(dirname "$dest")" ] || { [ -d "$dest" ] && [ -w "$dest" ]; }; then
    mkdir -p "$dest"
    cp -a "$src"/. "$dest"/
    return 0
  fi
  if sudo -n true 2>/dev/null; then
    sudo mkdir -p "$dest"
    sudo cp -a "$src"/. "$dest"/
    return 0
  fi
  record_manual "Install Tender plugin update" <<EOF
sudo mkdir -p '$dest'
sudo cp -a '$src'/. '$dest'/
$ROOT/scripts/ensure-eden-component.sh --wrap-launcher
# Then Decky → reload plugins (or leave Game Mode and come back).
EOF
  return 2
}

wrap_launcher() {
  "$ROOT/scripts/ensure-eden-component.sh" --wrap-launcher
}

have="$(installed_version || true)"
if [ "$DO_WRAP" -eq 1 ]; then
  wrap_launcher
  exit 0
fi

rel="$(latest_release || true)"
if [ -z "$rel" ]; then
  echo "Could not read Tender releases from GitHub ($TENDER_REPO)."
  record_manual "Update Tender from GitHub" <<EOF
# Official zip (Developer Mode → Install Plugin From URL, or this script):
# https://github.com/${TENDER_REPO}/releases/latest/download/Tender.zip
$ROOT/scripts/ensure-tender.sh
$ROOT/scripts/ensure-eden-component.sh --wrap-launcher
EOF
  [ "$DO_STATUS" -eq 1 ] || wrap_launcher || true
  exit 2
fi
tag="${rel%% *}"
zip_url="${rel#* }"
want="$(printf '%s' "$tag" | sed -E 's/^[Tt]ender-v//; s/^v//')"

echo "Tender installed: ${have:-none}"
echo "Tender wanted: ${want:-?} ($tag)"

if [ "$DO_STATUS" -eq 1 ]; then
  if [ -z "$have" ]; then
    echo "needs_update: yes (missing)"
    exit 2
  fi
  if version_lt "$have" "$want"; then
    echo "needs_update: yes"
    exit 2
  fi
  echo "needs_update: no"
  exit 0
fi

if [ -n "$have" ] && ! version_lt "$have" "$want"; then
  echo "Tender $have is current; re-applying rom-launcher wrap."
  wrap_launcher
  exit 0
fi

tmp="$(mktemp -d /tmp/tender-update-XXXXXX)"
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT

echo "Downloading $zip_url"
if ! curl -fsSL --max-time 120 -o "$tmp/Tender.zip" "$zip_url"; then
  echo "Tender zip download failed."
  wrap_launcher || true
  exit 2
fi
if ! unzip -q "$tmp/Tender.zip" -d "$tmp/extract"; then
  echo "Tender zip extract failed."
  wrap_launcher || true
  exit 2
fi
src=""
if [ -f "$tmp/extract/romm-tender/plugin.json" ]; then
  src="$tmp/extract/romm-tender"
elif [ -f "$tmp/extract/plugin.json" ]; then
  src="$tmp/extract"
else
  src="$(find "$tmp/extract" -name plugin.json -printf '%h\n' | head -1 || true)"
fi
if [ -z "$src" ] || [ ! -f "$src/plugin.json" ]; then
  echo "Tender zip has no plugin.json."
  wrap_launcher || true
  exit 1
fi
new_ver="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("version") or "")' "$src/plugin.json")"
echo "Installing Tender ${new_ver:-?} into $TENDER_PLUGIN_DIR"
if ! install_tree "$src" "$TENDER_PLUGIN_DIR"; then
  wrap_launcher || true
  exit 2
fi
wrap_launcher
if decky_reload_plugin "$TENDER_PLUGIN_NAME"; then
  echo "Reloaded $TENDER_PLUGIN_NAME in Decky (close and reopen QAM if it is already open)."
else
  echo "Copied Tender; reload Decky plugins (or leave Game Mode and come back)."
fi
echo "Tender is ${new_ver:-unknown} (was ${have:-none})."
exit 0
