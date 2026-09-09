#!/usr/bin/env bash
# Idempotently add Cemu / Azahar dual-screen apps to sunshine-ds-dev apps.json.
# Do not write Decky Flatpak apps.json (:47989).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"

APPS_JSON="${SUNSHINE_DS_APPS:-/home/${STEAMOS_USER:-deck}/.config/sunshine-ds-dev/sunshine/apps.json}"
CEMU_CMD="${STEAMOS_PLAYBOOK_DIR:-$ROOT}/scripts/sunshine-app-cemu.sh"
AZAHAR_CMD="${STEAMOS_PLAYBOOK_DIR:-$ROOT}/scripts/sunshine-app-azahar.sh"

if [ ! -f "$APPS_JSON" ]; then
  echo "Missing $APPS_JSON — start sunshine-ds once so it creates apps.json."
  exit 2
fi

python3 - "$APPS_JSON" "$CEMU_CMD" "$AZAHAR_CMD" "$ROOT/logs" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
cemu_cmd, azahar_cmd, log_dir = sys.argv[2], sys.argv[3], sys.argv[4]
data = json.loads(path.read_text())
apps = data.setdefault("apps", [])

wanted = {
    "Cemu Dual-Screen": {
        "name": "Cemu Dual-Screen",
        "cmd": cemu_cmd,
        "working-dir": str(Path(cemu_cmd).parent.parent),
        "output": str(Path(log_dir) / "sunshine-app-cemu.log"),
        "image-path": "desktop.png",
        "auto-detach": False,
        "wait-all": True,
        "exit-timeout": 10,
    },
    "Azahar Dual-Screen": {
        "name": "Azahar Dual-Screen",
        "cmd": azahar_cmd,
        "working-dir": str(Path(azahar_cmd).parent.parent),
        "output": str(Path(log_dir) / "sunshine-app-azahar.log"),
        "image-path": "desktop.png",
        "auto-detach": False,
        "wait-all": True,
        "exit-timeout": 10,
    },
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

chmod +x "$CEMU_CMD" "$AZAHAR_CMD"
echo "sunshine-ds apps are in $APPS_JSON (Moonlight :48100). Restart sunshine-ds to refresh the list if it is already running."
exit 0
