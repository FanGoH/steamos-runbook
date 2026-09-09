#!/usr/bin/env bash
# Idempotently add Cemu / Azahar dual-screen apps to sunshine-ds-dev apps.json.
# Do not write Decky Flatpak apps.json (:47989).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

APPS_JSON="${SUNSHINE_DS_APPS:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev/sunshine/apps.json}"
SUNSHINE_DS_CONF="${SUNSHINE_DS_CONF:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev/sunshine/sunshine.conf}"
CEMU_CMD="${STEAMOS_PLAYBOOK_DIR:-$ROOT}/scripts/sunshine-app-cemu.sh"
AZAHAR_CMD="${STEAMOS_PLAYBOOK_DIR:-$ROOT}/scripts/sunshine-app-azahar.sh"
STOP_CMD="${STEAMOS_PLAYBOOK_DIR:-$ROOT}/scripts/sunshine-app-stop.sh"

if [ ! -f "$APPS_JSON" ]; then
  echo "Missing $APPS_JSON — start sunshine-ds once so it creates apps.json."
  exit 2
fi

python3 "$ROOT/scripts/pad_profile.py" apply-sunshine-conf "$SUNSHINE_DS_CONF" || true

ICON_DIR="$(dirname "$APPS_JSON")/app-icons"
mkdir -p "$ICON_DIR"

python3 - "$APPS_JSON" "$CEMU_CMD" "$AZAHAR_CMD" "$STOP_CMD" "$ROOT/logs" "$ICON_DIR" <<'PY'
import json, shutil, struct, sys
from pathlib import Path

path = Path(sys.argv[1])
cemu_cmd, azahar_cmd, stop_cmd, log_dir = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
icon_dir = Path(sys.argv[6])
home = Path.home()
data = json.loads(path.read_text())
apps = data.setdefault("apps", [])
PNG = b"\x89PNG\r\n\x1a\n"


def png_wh(src: Path) -> tuple[int, int]:
    try:
        with src.open("rb") as fh:
            if fh.read(8) != PNG:
                return (0, 0)
            length, kind = struct.unpack(">I4s", fh.read(8))
            if kind != b"IHDR" or length < 8:
                return (0, 0)
            return struct.unpack(">II", fh.read(8))
    except OSError:
        return (0, 0)


def icon_candidates(filename: str) -> list[Path]:
    hicolors = [
        Path("/var/lib/flatpak/exports/share/icons/hicolor"),
        home / ".local/share/flatpak/exports/share/icons/hicolor",
    ]
    app_id = filename.removesuffix(".png")
    for prefix in (Path("/var/lib/flatpak/app"), home / ".local/share/flatpak/app"):
        hicolors.append(prefix / app_id / "current/active/export/share/icons/hicolor")
    found: list[Path] = []
    for root in hicolors:
        if not root.is_dir():
            continue
        found.extend(p for p in root.glob(f"*/apps/{filename}") if p.is_file())
    return found


def install_icon(dest_name: str, filename: str) -> str:
    dest = icon_dir / dest_name
    best = None
    best_area = -1
    for cand in icon_candidates(filename):
        w, h = png_wh(cand)
        area = w * h
        if area > best_area:
            best = cand
            best_area = area
    if best is None:
        print(f"No Flatpak PNG for {filename}; Moonlight will keep desktop.png", file=sys.stderr)
        return "desktop.png"
    icon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best, dest)
    print(f"Installed {dest} from {best} ({best_area} px)")
    return str(dest)


def spec(name, cmd, undo_target, image_path):
    return {
        "name": name,
        "cmd": cmd,
        "working-dir": str(Path(cmd).parent.parent),
        "output": str(Path(log_dir) / f"sunshine-app-{undo_target}.log"),
        "image-path": image_path,
        "auto-detach": False,
        "wait-all": True,
        "exit-timeout": 10,
        "prep-cmd": [
            {"do": "", "undo": f"{stop_cmd} {undo_target}"},
        ],
    }

cemu_icon = install_icon("cemu.png", "info.cemu.Cemu.png")
azahar_icon = install_icon("azahar.png", "org.azahar_emu.Azahar.png")
wanted = {
    "Cemu Dual-Screen": spec("Cemu Dual-Screen", cemu_cmd, "cemu", cemu_icon),
    "Azahar Dual-Screen": spec("Azahar Dual-Screen", azahar_cmd, "azahar", azahar_icon),
}

changed = False
by_name = {app.get("name"): i for i, app in enumerate(apps) if isinstance(app, dict)}
for name, spec in wanted.items():
    if name in by_name:
        idx = by_name[name]
        if apps[idx] != spec:
            apps[idx] = spec
            changed = True
            print("Updated", name, "in", path)
        else:
            print(name, "already installed in", path)
    else:
        apps.append(spec)
        changed = True
        print("Added", name, "to", path)

if changed:
    path.write_text(json.dumps(data, indent=2) + "\n")
PY

chmod +x "$CEMU_CMD" "$AZAHAR_CMD" "$STOP_CMD" "$ROOT/scripts/pad_profile.py"
echo "sunshine-ds apps are in $APPS_JSON (Moonlight :48100). Icons: $ICON_DIR. Restart sunshine-ds when the session is idle so Moonlight picks up new box art."
exit 0
