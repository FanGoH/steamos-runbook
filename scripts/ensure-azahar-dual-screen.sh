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
SDL_EXCEPT="$(python3 "$ROOT/scripts/pad_profile.py" sdl-except)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"
export DISPLAY="${DISPLAY:-:0}"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

PLACE_ONLY=0
if [ "${1:-}" = "--place-only" ]; then
  PLACE_ONLY=1
fi

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
export SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT='$SDL_EXCEPT'
flatpak run --env=QT_QPA_PLATFORM=xcb $AZAHAR_FLATPAK "<3ds>"
Then re-run: $ROOT/scripts/ensure-azahar-dual-screen.sh
EOF
}

if [ "$PLACE_ONLY" -eq 0 ]; then
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
fi

if [ "$PLACE_ONLY" -eq 0 ] && [ -f "$AZAHAR_INI" ]; then
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
WATCH_JS=""
if [ "$PLACE_ONLY" -eq 0 ]; then
  WATCH_JS='workspace.windowAdded.connect(function(w) { if (String(w.resourceClass || "") !== "Azahar") return; placeAll(); try { w.captionChanged.connect(function() { placeAll(); }); } catch (e) {} });'
fi
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
function azaharRole(w) {
    const cap = String(w.caption || "");
    if (cap.indexOf("Secondary Window") >= 0) return "secondary";
    if (cap.indexOf("Primary Window") >= 0) return "primary";
    const g = w.frameGeometry;
    if (!g || g.width < 50 || g.height < 50) return "skip";
    // Game views spawn ~400x480 / 400x240 before Azahar sets those captions.
    if (g.width <= 900 && g.height <= 700) {
        return g.height >= 400 ? "primary" : "secondary";
    }
    return "library";
}
function placeAll() {
    const tv = screenGeom("${TV_OUTPUT}");
    const pad = screenGeom("${PAD_OUTPUT}");
    if (!tv || !pad) {
        print("Azahar place: missing ${TV_OUTPUT} or ${PAD_OUTPUT}");
        return;
    }
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
    const azahar = [];
    let hasGame = false;
    for (const w of workspace.windowList()) {
        if (String(w.resourceClass || "") !== "Azahar") continue;
        azahar.push(w);
        const role = azaharRole(w);
        if (role === "primary" || role === "secondary") hasGame = true;
    }
    for (const w of azahar) {
        const role = azaharRole(w);
        if (role === "skip") continue;
        if (role === "secondary") raiseMove(w, pad);
        else if (role === "primary") raiseMove(w, tv);
        else if (hasGame) {
            try { w.minimized = true; } catch (e) {}
        } else {
            raiseMove(w, tv);
        }
    }
    print("Placed Azahar: top ${TV_OUTPUT} " + tv.x + "," + tv.y + " " + tv.width + "x" + tv.height + "; bottom ${PAD_OUTPUT} " + pad.x + "," + pad.y + " " + pad.width + "x" + pad.height);
}
placeAll();
${WATCH_JS}
EOF

place_windows() {
  local plugin
  if [ "$PLACE_ONLY" -eq 1 ]; then
    plugin="place-azahar-dual-screen-once"
  else
    plugin="place-azahar-dual-screen"
  fi
  busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting unloadScript s "$plugin" >/dev/null 2>&1 || true
  if busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting loadScript ss "$PLACE_JS" "$plugin" >/dev/null &&
     busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting start >/dev/null; then
    echo "Placed Azahar: Primary ${TV_OUTPUT}; Secondary ${PAD_OUTPUT} (geometry from KWin screens)"
    if [ "$PLACE_ONLY" -eq 1 ]; then
      busctl --user call org.kde.KWin /Scripting org.kde.kwin.Scripting unloadScript s "$plugin" >/dev/null 2>&1 || true
    fi
    return 0
  fi
  echo "Could not load the KWin place script (is this a Plasma session?)."
  return 2
}

if [ "$PLACE_ONLY" -eq 1 ]; then
  place_windows || exit 2
  exit 0
fi

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
    --env=SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT="$SDL_EXCEPT" \
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
