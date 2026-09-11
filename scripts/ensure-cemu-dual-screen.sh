#!/usr/bin/env bash
# Place standalone Cemu for desktop dual-stream: TV on HDMI, GamePad on Virtual-sunshine-ds.
# Binds player 0 to EmuPads P1 (mux). Do not --match a Sunshine pad into XML.
# Launches a ROM only when CEMU_ROM is set and Cemu is not already running.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

STEAMOS_USER="${STEAMOS_USER:-deck}"
CEMU_SETTINGS="${CEMU_SETTINGS:-/home/${STEAMOS_USER}/.var/app/info.cemu.Cemu/config/Cemu/settings.xml}"
CEMU_CONTROLLER="${CEMU_CONTROLLER:-/home/${STEAMOS_USER}/.var/app/info.cemu.Cemu/config/Cemu/controllerProfiles/controller0.xml}"
TV_OUTPUT="${CEMU_TV_OUTPUT:-HDMI-A-1}"
PAD_OUTPUT="${CEMU_PAD_OUTPUT:-Virtual-sunshine-ds}"
PAD_MATCH="${CEMU_PAD_MATCH:-Thor}"
SDL_EXCEPT="$(python3 "$ROOT/scripts/pad_profile.py" sdl-except-sinks)"
SDL_BLACKLIST_EXCEPT="$SDL_EXCEPT"
SDL_BLACKLIST="0x1209/0x0003"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
export DISPLAY="${DISPLAY:-:0}"

cemu_running() {
  ps -eo comm= | grep -Eq '^[Cc]emu'
}

sdl_launch_env() {
  export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
  export SDL_JOYSTICK_HIDAPI=0
  export SDL_HIDAPI_JOYSTICK=0
  unset SDL_GAMECONTROLLER_IGNORE_DEVICES
  export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$SDL_EXCEPT"
  export SDL_JOYSTICK_BLACKLIST_DEVICES_EXCEPT="$SDL_BLACKLIST_EXCEPT"
  export SDL_JOYSTICK_BLACKLIST_DEVICES="$SDL_BLACKLIST"
}

print_launch_hint() {
  record_manual "Launch standalone Cemu (not RetroDECK)" <<EOF
export XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR WAYLAND_DISPLAY=$WAYLAND_DISPLAY
export DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS DISPLAY=:0
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='$SDL_EXCEPT'
export SDL_JOYSTICK_BLACKLIST_DEVICES_EXCEPT='$SDL_BLACKLIST_EXCEPT'
export SDL_JOYSTICK_BLACKLIST_DEVICES='$SDL_BLACKLIST'
flatpak run info.cemu.Cemu -g "<wux>"
Then re-run: $ROOT/scripts/ensure-cemu-dual-screen.sh
EOF
}

if ! command -v kscreen-doctor >/dev/null; then
  echo "kscreen-doctor is required."
  exit 1
fi

eval "$(python3 - "$TV_OUTPUT" "$PAD_OUTPUT" <<'PY'
import json, subprocess, sys
tv_name, pad_name = sys.argv[1], sys.argv[2]
raw = subprocess.check_output(["kscreen-doctor", "-j"], text=True)
data = json.loads(raw)
tv = pad = None
for o in data.get("outputs", []):
    name = o.get("name")
    geo = o.get("pos", {})
    size = o.get("size", {})
    enabled = o.get("enabled", False)
    rec = (name, int(geo.get("x", 0)), int(geo.get("y", 0)),
           int(size.get("width", 0)), int(size.get("height", 0)), enabled)
    if name == tv_name:
        tv = rec
    elif name == pad_name:
        pad = rec
if not tv or not tv[5] or tv[3] <= 0:
    sys.stderr.write("HDMI/TV output %s is missing or disabled\n" % tv_name)
    sys.exit(1)
if not pad or not pad[5] or pad[3] <= 0:
    sys.stderr.write("Virtual GamePad output %s is missing. Keep sunshine-ds-virtual-output running.\n" % pad_name)
    sys.exit(1)
print("TV_X=%d TV_Y=%d TV_W=%d TV_H=%d" % (tv[1], tv[2], tv[3], tv[4]))
print("PAD_X=%d PAD_Y=%d PAD_W=%d PAD_H=%d" % (pad[1], pad[2], pad[3], pad[4]))
PY
)"

python3 - "$CEMU_SETTINGS" "$TV_X" "$TV_Y" "$TV_W" "$TV_H" "$PAD_X" "$PAD_Y" "$PAD_W" "$PAD_H" <<'PY'
import sys, xml.etree.ElementTree as ET
from pathlib import Path
path = Path(sys.argv[1])
nums = list(map(int, sys.argv[2:]))
if not path.is_file():
    sys.stderr.write("Missing %s\n" % path)
    sys.exit(1)

def set_xy(parent, tag, x, y):
    node = parent.find(tag)
    if node is None:
        node = ET.SubElement(parent, tag)
    for name, val in (("x", x), ("y", y)):
        child = node.find(name)
        if child is None:
            child = ET.SubElement(node, name)
        child.text = str(val)

tree = ET.parse(path)
root = tree.getroot()
for tag, val in (("fullscreen", "false"), ("open_pad", "true")):
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    node.text = val
set_xy(root, "window_position", nums[0], nums[1])
set_xy(root, "window_size", nums[2], nums[3])
set_xy(root, "pad_position", nums[4], nums[5])
set_xy(root, "pad_size", nums[6], nums[7])
tree.write(path, encoding="UTF-8", xml_declaration=True)
print("Wrote Cemu window/pad geometry in", path)
PY

if [ -f "$CEMU_CONTROLLER" ]; then
  if ! grep -q "<type>Wii U GamePad</type>" "$CEMU_CONTROLLER"; then
    echo "controller0.xml is not Wii U GamePad. Stop Cemu, set <type>Wii U GamePad</type>, start again."
    exit 2
  fi
  bind_rc=0
  python3 "$ROOT/scripts/bind-gamepad.py" apply --emu cemu --xml "$CEMU_CONTROLLER" --force \
    || bind_rc=$?
  if [ "$bind_rc" -ne 0 ]; then
    echo "Could not bind Cemu player 0. Connected pads:"
    python3 "$ROOT/scripts/bind-gamepad.py" list || true
  fi
fi

RULE_ID="$(kreadconfig6 --file kwinrulesrc --group General --key rules 2>/dev/null || true)"
if [ -z "$RULE_ID" ]; then
  RULE_ID="$(uuidgen)"
  kwriteconfig6 --file kwinrulesrc --group General --key rules "$RULE_ID"
fi
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key Description "Cemu keep above (GameStream)"
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key above true --type bool
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key aboverule 2
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key noborder true --type bool
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key noborderrule 2
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key types 0
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key wmclass "info.cemu.Cemu"
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key wmclasscomplete false --type bool
kwriteconfig6 --file kwinrulesrc --group "$RULE_ID" --key wmclassmatch 1
qdbus org.kde.KWin /KWin org.kde.KWin.reconfigure >/dev/null 2>&1 || true

PLACE_JS="${XDG_RUNTIME_DIR}/place-cemu-dual-screen.js"
cat >"$PLACE_JS" <<EOF
for (const w of workspace.windowList()) {
    const res = String(w.resourceClass || "").toLowerCase();
    const cap = String(w.caption || "").toLowerCase();
    if (res === "steam" || cap.indexOf("steam") >= 0) {
        try { w.minimized = true; } catch (e) {}
    }
}
function raiseMove(w, outputName, x, y, width, height) {
    const screens = {};
    for (const s of workspace.screens) screens[s.name] = s;
    try { w.minimized = false; } catch (e) {}
    try { w.keepAbove = true; } catch (e) {}
    try { w.noBorder = true; } catch (e) {}
    if (screens[outputName]) { try { w.output = screens[outputName]; } catch (e) {} }
    try { w.frameGeometry = { x: x, y: y, width: width, height: height }; } catch (e) {}
}
for (const w of workspace.windowList()) {
    const cap = String(w.caption || "");
    const res = String(w.resourceClass || "");
    if (cap.indexOf("GamePad View") >= 0) {
        raiseMove(w, "${PAD_OUTPUT}", ${PAD_X}, ${PAD_Y}, ${PAD_W}, ${PAD_H});
    } else if (res === "info.cemu.Cemu") {
        raiseMove(w, "${TV_OUTPUT}", ${TV_X}, ${TV_Y}, ${TV_W}, ${TV_H});
    }
}
EOF

place_windows() {
  if busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting loadScript s "$PLACE_JS" >/dev/null &&
     busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting start >/dev/null; then
    echo "Placed Cemu: TV ${TV_OUTPUT} ${TV_X},${TV_Y} ${TV_W}x${TV_H}; GamePad ${PAD_OUTPUT} ${PAD_X},${PAD_Y} ${PAD_W}x${PAD_H}"
    return 0
  fi
  echo "Could not load the KWin place script (is this a Plasma session?)."
  return 2
}

if ! cemu_running; then
  if [ -z "${CEMU_ROM:-}" ] && [ "${CEMU_ALLOW_LIBRARY:-}" != 1 ]; then
    print_launch_hint
    exit 2
  fi
  mkdir -p "$ROOT/logs"
  sdl_launch_env
  if [ -n "${CEMU_ROM:-}" ]; then
    echo "Launching standalone Cemu with CEMU_ROM."
    cemu_args=(-g "$CEMU_ROM")
  else
    echo "Launching standalone Cemu library (CEMU_ALLOW_LIBRARY=1, no ROM)."
    cemu_args=()
  fi
  nohup flatpak run \
    --env=SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1 \
    --env=SDL_JOYSTICK_HIDAPI=0 \
    --env=SDL_HIDAPI_JOYSTICK=0 \
    --env=SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$SDL_EXCEPT" \
    --env=SDL_JOYSTICK_BLACKLIST_DEVICES_EXCEPT="$SDL_BLACKLIST_EXCEPT" \
    --env=SDL_JOYSTICK_BLACKLIST_DEVICES="$SDL_BLACKLIST" \
    info.cemu.Cemu "${cemu_args[@]}" \
    >>"$ROOT/logs/cemu-dual-screen.log" 2>&1 &
  waited=0
  while [ "$waited" -lt 25 ]; do
    if cemu_running; then
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  if ! cemu_running; then
    echo "Cemu did not start. See $ROOT/logs/cemu-dual-screen.log"
    print_launch_hint
    exit 2
  fi
  sleep 3
fi

place_windows || exit 2
echo "Cemu dual-screen layout applied."
exit 0
