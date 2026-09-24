#!/usr/bin/env bash
# Download a host mpv AppImage for Switch 2 capture (V4L2 needs host ACLs;
# Flatpak io.mpv.Mpv cannot open /dev/videoN as user deck).
# Idempotent. Does not touch pacman / steamos-readonly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT" 2>/dev/null || true

APPDIR="${SWITCH2_MPV_APPDIR:-/home/${STEAMOS_USER:-deck}/AppImages}"
LINK="${SWITCH2_MPV_LINK:-/home/${STEAMOS_USER:-deck}/.local/bin/mpv-switch2}"
REPO="${SWITCH2_MPV_REPO:-ivan-hc/MPV-appimage}"
API="https://api.github.com/repos/${REPO}/releases/latest"

mkdir -p "$APPDIR" "$(dirname "$LINK")"

if [ -x "$LINK" ]; then
  echo "ok: $LINK → $(readlink -f "$LINK" 2>/dev/null || echo "$LINK")"
  "$LINK" --version 2>&1 | head -n1 || true
  exit 0
fi

# Reuse an existing AppImage if present
existing="$(ls -1t "$APPDIR"/mpv*.AppImage 2>/dev/null | head -n1 || true)"
if [ -n "$existing" ] && [ -x "$existing" ]; then
  ln -sfn "$existing" "$LINK"
  echo "ok: linked existing $existing → $LINK"
  exit 0
fi

echo "Fetching latest mpv AppImage from ${REPO}…"
tmp="$(mktemp)"
curl -fsSL "$API" -o "$tmp"
read -r url name < <(python3 - "$tmp" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
assets = r.get("assets") or []
cands = [a for a in assets if a["name"].endswith(".AppImage") and "x86_64" in a["name"].lower()]
if not cands:
    cands = [a for a in assets if a["name"].endswith(".AppImage")]
if not cands:
    raise SystemExit("no AppImage asset in release")
a = cands[0]
print(a["browser_download_url"], a["name"])
PY
)
rm -f "$tmp"

dest="$APPDIR/$name"
echo "Downloading $name …"
curl -fL --progress-bar -o "$dest" "$url"
chmod +x "$dest"
ln -sfn "$dest" "$LINK"
echo "ok: $LINK → $dest"
"$LINK" --version 2>&1 | head -n1 || true
