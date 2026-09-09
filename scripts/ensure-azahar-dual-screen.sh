#!/usr/bin/env bash
# Place standalone Azahar for desktop dual-stream: 3DS top on HDMI, bottom on Virtual-sunshine-ds.
# Binds SDL mappings with bind-gamepad.py. Qt Wayland crashes (drm_syncobj); launch with xcb.
# Launches a ROM only when AZAHAR_ROM is set and Azahar is not already running.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

STEAMOS_USER="${STEAMOS_USER:-deck}"
AZAHAR_INI="${AZAHAR_INI:-/home/${STEAMOS_USER}/.var/app/org.azahar_emu.Azahar/config/azahar-emu/qt-config.ini}"
AZAHAR_FLATPAK="${AZAHAR_FLATPAK:-org.azahar_emu.Azahar}"
TV_OUTPUT="${CEMU_TV_OUTPUT:-HDMI-A-1}"
PAD_OUTPUT="${CEMU_PAD_OUTPUT:-Virtual-sunshine-ds}"
PAD_MATCH="${AZAHAR_PAD_MATCH:-${CEMU_PAD_MATCH:-Thor}}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
export DISPLAY="${DISPLAY:-:0}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

azahar_running() {
  ps -eo comm= | grep -qx azahar
}

print_launch_hint() {
  record_manual "Launch standalone Azahar (not RetroDECK)" <<EOF
export XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR WAYLAND_DISPLAY=$WAYLAND_DISPLAY
export DBUS_SESSION_BUS_ADDRESS=$DBUS_SESSION_BUS_ADDRESS DISPLAY=:0 QT_QPA_PLATFORM=xcb
export SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1
export SDL_JOYSTICK_HIDAPI=0 SDL_HIDAPI_JOYSTICK=0
unset SDL_GAMECONTROLLER_IGNORE_DEVICES
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009'
flatpak run --env=QT_QPA_PLATFORM=xcb $AZAHAR_FLATPAK "<3ds>"
Then re-run: $ROOT/scripts/ensure-azahar-dual-screen.sh
EOF
}

python3 - "$AZAHAR_INI" <<'PY'
import re, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.is_file():
    sys.stderr.write("Missing %s\n" % path)
    sys.exit(1)
text = path.read_text()

def set_key(src, key, value):
    pat = re.compile(r"^" + re.escape(key) + r"=.*$", re.M)
    repl = f"{key}={value}"
    if pat.search(src):
        src = pat.sub(lambda _m: repl, src, count=1)
    else:
        src += f"\n{repl}\n"
    dkey = key + "\\default"
    dpat = re.compile(r"^" + re.escape(dkey) + r"=.*$", re.M)
    drepl = dkey + "=false"
    if dpat.search(src):
        src = dpat.sub(lambda _m: drepl, src, count=1)
    return src

for key, val in [
    ("layout_option", "4"),
    ("secondary_display_layout", "2"),
    ("fullscreen", "false"),
    ("singleWindowMode", "false"),
    ("confirmClose", "false"),
    ("pauseWhenInBackground", "false"),
    ("screen_bottom_stretch", "true"),
    ("screen_top_stretch", "true"),
]:
    text = set_key(text, key, val)
path.write_text(text)
print("Wrote Azahar separate-windows layout in", path)
PY

if [ -f "$AZAHAR_INI" ]; then
  bind_rc=0
  if ! python3 "$ROOT/scripts/bind-gamepad.py" azahar --ini "$AZAHAR_INI" --match "$PAD_MATCH" --force; then
    if [ "$PAD_MATCH" != Sunshine ]; then
      echo "No pad matched ${PAD_MATCH}; trying Sunshine."
      python3 "$ROOT/scripts/bind-gamepad.py" azahar --ini "$AZAHAR_INI" --match Sunshine --force || bind_rc=$?
    else
      bind_rc=1
    fi
  fi
  if [ "$bind_rc" -ne 0 ]; then
    echo "Could not bind Azahar. Connected pads:"
    python3 "$ROOT/scripts/bind-gamepad.py" list || true
  fi
fi

PLACE_JS="${XDG_RUNTIME_DIR}/place-azahar-dual-screen.js"
cat >"$PLACE_JS" <<EOF
function screenGeom(name) {
    for (const s of workspace.screens) {
        if (s.name === name) {
            const g = s.geometry;
            return { x: g.x, y: g.y, width: g.width, height: g.height, screen: s };
        }
    }
    return null;
}
const tv = screenGeom("${TV_OUTPUT}");
const pad = screenGeom("${PAD_OUTPUT}");
if (!tv || !pad) {
    print("Azahar place: missing ${TV_OUTPUT} or ${PAD_OUTPUT}");
} else {
    for (const w of workspace.windowList()) {
        const res = String(w.resourceClass || "").toLowerCase();
        const cap = String(w.caption || "").toLowerCase();
        if (res === "steam" || cap.indexOf("steam") >= 0) {
            try { w.minimized = true; } catch (e) {}
        }
    }
    function raiseMove(w, geom) {
        try { w.minimized = false; } catch (e) {}
        try { w.keepAbove = true; } catch (e) {}
        try { w.noBorder = true; } catch (e) {}
        try { w.output = geom.screen; } catch (e) {}
        try { w.frameGeometry = { x: geom.x, y: geom.y, width: geom.width, height: geom.height }; } catch (e) {}
    }
    for (const w of workspace.windowList()) {
        const cap = String(w.caption || "");
        const res = String(w.resourceClass || "");
        if (res !== "Azahar") continue;
        if (cap.indexOf("Secondary Window") >= 0) {
            raiseMove(w, pad);
        } else if (cap.indexOf("Primary Window") >= 0) {
            raiseMove(w, tv);
        } else {
            try { w.minimized = true; } catch (e) {}
        }
    }
    print("Placed Azahar: top ${TV_OUTPUT} " + tv.x + "," + tv.y + " " + tv.width + "x" + tv.height + "; bottom ${PAD_OUTPUT} " + pad.x + "," + pad.y + " " + pad.width + "x" + pad.height);
}
EOF

place_windows() {
  if busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting loadScript s "$PLACE_JS" >/dev/null &&
     busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting start >/dev/null; then
    echo "Placed Azahar: Primary ${TV_OUTPUT}; Secondary ${PAD_OUTPUT} (geometry from KWin screens)"
    return 0
  fi
  echo "Could not load the KWin place script (is this a Plasma session?)."
  return 2
}

if ! azahar_running; then
  if [ -z "${AZAHAR_ROM:-}" ] && [ "${AZAHAR_ALLOW_LIBRARY:-}" != 1 ]; then
    print_launch_hint
    exit 2
  fi
  mkdir -p "$ROOT/logs"
  if [ -n "${AZAHAR_ROM:-}" ]; then
    echo "Launching standalone Azahar with AZAHAR_ROM (QT_QPA_PLATFORM=xcb)."
    azahar_args=("$AZAHAR_ROM")
  else
    echo "Launching standalone Azahar library (AZAHAR_ALLOW_LIBRARY=1, no ROM, QT_QPA_PLATFORM=xcb)."
    azahar_args=()
  fi
  nohup flatpak run \
    --env=QT_QPA_PLATFORM=xcb \
    --env=SDL_GAMECONTROLLER_ALLOW_STEAM_VIRTUAL_GAMEPAD=1 \
    --env=SDL_JOYSTICK_HIDAPI=0 \
    --env=SDL_HIDAPI_JOYSTICK=0 \
    --env=SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='0x28de/0x11ff,0x045e/0x02ea,0x045e/0x028e,0x045e/0x02fd,0x057e/0x2009' \
    "$AZAHAR_FLATPAK" "${azahar_args[@]}" \
    >>"$ROOT/logs/azahar-dual-screen.log" 2>&1 &
  waited=0
  while [ "$waited" -lt 25 ]; do
    if azahar_running; then
      break
    fi
    sleep 1
    waited=$((waited + 1))
  done
  if ! azahar_running; then
    echo "Azahar did not start. See $ROOT/logs/azahar-dual-screen.log"
    print_launch_hint
    exit 2
  fi
  sleep 6
fi

place_windows || exit 2
echo "Azahar dual-screen layout applied."
exit 0
