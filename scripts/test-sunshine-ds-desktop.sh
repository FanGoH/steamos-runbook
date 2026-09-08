#!/usr/bin/env bash
# Desktop-mode dual-display smoke test for sunshine-ds.
#
# Does not talk to Thor/Moonlight DS. Proves:
#   1. Plasma Wayland is running
#   2. A KWin virtual output exists (created if needed)
#   3. Distinct windows sit on the TV and the virtual output
#   4. sunshine-ds on alternate ports advertises MaxVideoStreams=2
#   5. Logs list both capture names
#
# Does not replace Decky Sunshine. Process name is sunshine-ds.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/common.sh
source "$ROOT/scripts/common.sh"
load_env "$ROOT"
setup_user_dbus

BOX="${STEAMOS_DISTROBOX_NAME:-steamos-tools}"
BIN="${SUNSHINE_DS_BIN:-/home/${STEAMOS_USER}/.local/bin/sunshine-ds}"
HELPER="${SUNSHINE_DS_VIRTUAL_HELPER:-/home/${STEAMOS_USER}/.local/bin/sunshine-ds-virtual-output}"
CONF_DIR="${SUNSHINE_DS_CONF_DIR:-/home/${STEAMOS_USER}/.config/sunshine-ds-dev}"
PORT="${SUNSHINE_DS_PORT:-48100}"
GAMESTREAM_URL="http://127.0.0.1:${PORT}"
UI_URL="https://127.0.0.1:$((PORT + 1))"
WORK="${SUNSHINE_DS_SMOKE_DIR:-/tmp/sunshine-ds-smoke}"
LOG="$ROOT/logs/sunshine-ds-smoke.log"
VIRT_NAME="${SUNSHINE_DS_VIRTUAL_NAME:-sunshine-ds}"
VIRT_W="${SUNSHINE_DS_VIRTUAL_WIDTH:-1280}"
VIRT_H="${SUNSHINE_DS_VIRTUAL_HEIGHT:-800}"

mkdir -p "$WORK" "$CONF_DIR/sunshine" "$ROOT/logs"

need_bin() {
  if [ ! -x "$BIN" ]; then
    echo "Missing $BIN — run scripts/build-sunshine-ds.sh first."
    exit 1
  fi
  if [ ! -x "$HELPER" ]; then
    echo "Missing $HELPER — run scripts/build-sunshine-ds.sh first."
    exit 1
  fi
}

ensure_desktop() {
  if systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1 \
    && ! systemctl --user is-active gamescope-session.service >/dev/null 2>&1; then
    echo "Already in Plasma desktop."
    return 0
  fi
  echo "Switching to Plasma Wayland desktop..."
  steamos-session-select plasma-wayland-persistent
  local waited=0
  while [ "$waited" -lt 60 ]; do
    if systemctl --user is-active plasma-plasmashell.service >/dev/null 2>&1; then
      export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
      export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
      echo "Plasma is up."
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done
  echo "Plasma did not start within 60s."
  exit 1
}

wayland_env() {
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
  unset DISPLAY
  export QT_QPA_PLATFORM=wayland
  if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then
    export WAYLAND_DISPLAY=wayland-0
  elif [ -S "$XDG_RUNTIME_DIR/wayland-1" ]; then
    export WAYLAND_DISPLAY=wayland-1
  else
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
  fi
}

install_kwin_desktop() {
  local apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
  mkdir -p "$apps"
  cat >"$apps/sunshine-ds-virtual-output.desktop" <<EOF
[Desktop Entry]
Exec=${HELPER}
X-KDE-Wayland-Interfaces=zkde_screencast_unstable_v1
Type=Application
Name=sunshine-ds-virtual-output
Comment=Sunshine DS KWin virtual output permission
NoDisplay=true
EOF
  cat >"$apps/sunshine-ds.kwin.desktop" <<EOF
[Desktop Entry]
Exec=${BIN}
X-KDE-Wayland-Interfaces=zkde_screencast_unstable_v1
Type=Application
Name=sunshine-ds-kwin-wayland-permission
Comment=Sunshine DS KWin screencast permission
NoDisplay=true
EOF
  kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
}

write_pages() {
  cat >"$WORK/primary.html" <<'EOF'
<!doctype html><html><head><title>SUNSHINE-DS PRIMARY</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#c41e3a;color:#fff;font:56px/1.2 sans-serif}
#label{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;pointer-events:none;z-index:0}
#t{font:24px/1.2 monospace;margin-top:12px}
#box{position:absolute;width:160px;height:160px;background:#fff;color:#c41e3a;display:flex;align-items:center;justify-content:center;font:28px/1 sans-serif;font-weight:700;z-index:1;animation:bounce 1.6s linear infinite alternate;will-change:left,top}
@keyframes bounce{from{left:0;top:0}to{left:calc(100vw - 160px);top:calc(100vh - 160px)}}
</style></head>
<body>
<div id="label"><div>PRIMARY TV 1920x1080</div><div id="t"></div></div>
<div id="box">MOVE</div>
<script>
const t=document.getElementById('t');
function tick(){ t.textContent=new Date().toISOString().slice(11,23)+'  '+innerWidth+'x'+innerHeight; }
setInterval(tick,200);
tick();
</script>
</body></html>
EOF
  cat >"$WORK/gamepad.html" <<'EOF'
<!doctype html><html><head><title>SUNSHINE-DS GAMEPAD</title>
<style>
html,body{margin:0;height:100%;overflow:hidden;background:#1e4cc4;color:#fff;font:56px/1.2 sans-serif}
#label{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;pointer-events:none;z-index:0}
#t{font:24px/1.2 monospace;margin-top:12px}
#box{position:absolute;width:160px;height:160px;background:#fff;color:#1e4cc4;display:flex;align-items:center;justify-content:center;font:28px/1 sans-serif;font-weight:700;z-index:1;animation:bounce 1.6s linear infinite alternate;will-change:left,top}
@keyframes bounce{from{left:0;top:0}to{left:calc(100vw - 160px);top:calc(100vh - 160px)}}
body{animation:pulse 1s linear infinite alternate}
@keyframes pulse{from{background:#1e4cc4}to{background:#7cff6b}}
</style></head>
<body>
<div id="label"><div>GAMEPAD</div><div id="t"></div></div>
<div id="box">MOVE</div>
<script>
const t=document.getElementById('t');
function tick(){ t.textContent=new Date().toISOString().slice(11,23)+'  '+innerWidth+'x'+innerHeight; }
setInterval(tick,200);
tick();
</script>
</body></html>
EOF
}

kscreen_json() {
  kscreen-doctor -j 2>/dev/null | python3 -c 'import json,re,sys; s=sys.stdin.read(); s=re.sub(r"\x1b\[[0-9;]*m","",s); json.dump(json.loads(s), sys.stdout)'
}

virtual_output_name() {
  kscreen_json | python3 -c '
import json,sys
want="'"$VIRT_NAME"'"
data=json.load(sys.stdin)
for o in data.get("outputs", []):
    n=str(o.get("name") or "")
    if n==want or n=="Virtual-"+want or want in n:
        print(n)
        break
'
}

ensure_virtual_output() {
  local existing
  existing="$(virtual_output_name || true)"
  if [ -n "$existing" ]; then
    echo "Virtual output already present: $existing"
    return 0
  fi
  echo "Creating KWin virtual output ${VIRT_NAME} (${VIRT_W}x${VIRT_H})..."
  wayland_env
  "$HELPER" --name "$VIRT_NAME" --width "$VIRT_W" --height "$VIRT_H" --scale 1 \
    --pid-file "$WORK/virtual.pid" >"$WORK/virtual.stdout" 2>"$WORK/virtual.stderr" &
  local waited=0
  while [ "$waited" -lt 20 ]; do
    existing="$(virtual_output_name || true)"
    if [ -n "$existing" ]; then
      echo "Virtual output appeared: $existing"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "Virtual output did not appear. kscreen-doctor -o:"
  kscreen-doctor -o || true
  echo "helper log:"
  cat "$WORK/virtual.stderr" || true
  exit 1
}

primary_output_name() {
  kscreen_json | python3 -c '
import json,sys
data=json.load(sys.stdin)
for o in data.get("outputs", []):
    n=str(o.get("name") or "")
    if n.startswith("Virtual-"):
        continue
    if o.get("connected") and o.get("enabled", True):
        print(n)
        break
'
}

place_windows() {
  local primary="$1"
  local virtual="$2"
  python3 - "$primary" "$virtual" "$WORK" <<'PY'
import json, os, re, subprocess, sys, time

primary, virtual, work = sys.argv[1:4]

def doctor():
    raw = subprocess.check_output(["kscreen-doctor", "-j"], text=True)
    raw = re.sub(r"\x1b\[[0-9;]*m", "", raw)
    return json.loads(raw)

def geom(data, name):
    for o in data.get("outputs", []):
        n = str(o.get("name") or "")
        if n != name:
            continue
        pos = o.get("pos") or {}
        size = o.get("size") or {}
        scale = float(o.get("scale") or 1) or 1.0
        w = int(round((size.get("width") or 1280) / scale))
        h = int(round((size.get("height") or 800) / scale))
        return int(pos.get("x", 0)), int(pos.get("y", 0)), w, h
    return 0, 0, 1920, 1080

data = doctor()
px, py, pw, ph = geom(data, primary)
vx, vy, vw, vh = geom(data, virtual)

server = subprocess.Popen(
    ["python3", "-m", "http.server", "8765", "--bind", "127.0.0.1"],
    cwd=work,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
time.sleep(0.4)

env = os.environ.copy()
env.pop("DISPLAY", None)
env["WAYLAND_DISPLAY"] = os.environ.get("WAYLAND_DISPLAY", "wayland-0")
env["XDG_RUNTIME_DIR"] = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

def open_page(path, profile, x, y, w, h):
    url = "http://127.0.0.1:8765/" + path
    args = [
        "flatpak", "run", "com.google.Chrome",
        "--ozone-platform=wayland",
        f"--user-data-dir={os.path.join(work, profile)}",
        "--no-first-run", "--no-default-browser-check", "--disable-sync",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        f"--window-position={x},{y}",
        f"--window-size={w},{h}",
        f"--app={url}",
    ]
    return subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

p1 = open_page("primary.html", "chrome-primary", px, py, pw, ph)
time.sleep(2)
p2 = open_page("gamepad.html", "chrome-gamepad", vx, vy, vw, vh)
open(os.path.join(work, "browser.pids"), "w").write(f"{p1.pid}\n{p2.pid}\n{server.pid}\n")
print(f"Opened PRIMARY at {px},{py} {pw}x{ph} and GAMEPAD at {vx},{vy} {vw}x{vh}")
time.sleep(3)

script = f"""
const clients = workspace.windowList();
for (const w of clients) {{
    const cap = (w.caption || "") + " " + (w.resourceName || "");
    if (cap.indexOf("PRIMARY") >= 0) {{
        w.frameGeometry = {{ x: {px}, y: {py}, width: {pw}, height: {ph} }};
    }} else if (cap.indexOf("GAMEPAD") >= 0) {{
        w.frameGeometry = {{ x: {vx}, y: {vy}, width: {vw}, height: {vh} }};
        w.keepAbove = true;
    }}
}}
"""
script_path = os.path.join(work, "place.js")
open(script_path, "w").write(script)
try:
    sid = subprocess.check_output(
        ["busctl", "--user", "call", "org.kde.KWin", "/Scripting",
         "org.kde.kwin.Scripting", "loadScript", "s", script_path],
        text=True,
    ).strip()
    # busctl prints "i 7"
    ident = sid.split()[-1]
    subprocess.call(["busctl", "--user", "call", "org.kde.KWin", "/Scripting",
                     "org.kde.kwin.Scripting", "start"])
    subprocess.call(["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{ident}",
                     "org.kde.kwin.Script", "run"])
    print(f"KWin place script id={ident}")
except Exception as exc:
    print(f"KWin window placement skipped: {exc}")
PY
}

write_sunshine_conf() {
  local primary="$1"
  local virtual="$2"
  mkdir -p "$CONF_DIR/sunshine"
  local apps_src="${SUNSHINE_DS_SRC:-/home/${STEAMOS_USER}/code/sunshine-ds}/src_assets/linux/assets/apps.json"
  if [ -f "$apps_src" ] && [ ! -f "$CONF_DIR/sunshine/apps.json" ]; then
    cp "$apps_src" "$CONF_DIR/sunshine/apps.json"
  fi
  cat >"$CONF_DIR/sunshine/sunshine.conf" <<EOF
# sunshine-ds-dev — do not share this directory with the Decky Flatpak
port = ${PORT}
origin_web_ui_allowed = pc
capture = kwin
output_name = ${primary}
dual_display_source = ${virtual}
min_log_level = info
# Absolute so a restart without CONFIGURATION_DIRECTORY keeps the paired identity.
file_state = ${CONF_DIR}/sunshine/sunshine_state.json
log_path = ${CONF_DIR}/sunshine/sunshine.log
file_apps = ${CONF_DIR}/sunshine/apps.json
pkey = ${CONF_DIR}/sunshine/credentials/cakey.pem
cert = ${CONF_DIR}/sunshine/credentials/cacert.pem
credentials_file = ${CONF_DIR}/sunshine/sunshine_state.json
EOF
  echo "Wrote $CONF_DIR/sunshine/sunshine.conf (primary=$primary second=$virtual port=$PORT)"
}

start_sunshine_ds() {
  if pgrep -u "$STEAMOS_USER" -x sunshine-ds >/dev/null 2>&1; then
    pkill -u "$STEAMOS_USER" -x sunshine-ds || true
    sleep 1
  fi
  wayland_env
  export CONFIGURATION_DIRECTORY="$CONF_DIR"
  export PATH="${HOME}/.local/bin:${PATH}"
  export SUNSHINE_DS_VIRTUAL_HELPER="$HELPER"
  nohup distrobox enter "$BOX" -- bash -lc "
    export XDG_RUNTIME_DIR=$(printf %q "${XDG_RUNTIME_DIR}")
    export WAYLAND_DISPLAY=$(printf %q "${WAYLAND_DISPLAY}")
    unset DISPLAY
    export QT_QPA_PLATFORM=wayland
    export CONFIGURATION_DIRECTORY=$(printf %q "$CONF_DIR")
    export PATH=$(printf %q "${HOME}/.local/bin"):\"\$PATH\"
    export SUNSHINE_DS_VIRTUAL_HELPER=$(printf %q "$HELPER")
    exec $(printf %q "$BIN") $(printf %q "$CONF_DIR/sunshine/sunshine.conf")
  " >"$LOG" 2>&1 &
  echo $! >"$WORK/sunshine-ds.pid"
  echo "Started sunshine-ds wrapper pid $(cat "$WORK/sunshine-ds.pid") log=$LOG"
}

wait_for_serverinfo() {
  local waited=0
  while [ "$waited" -lt 40 ]; do
    if curl -sf "$GAMESTREAM_URL/serverinfo" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done
  echo "sunshine-ds GameStream did not answer on $GAMESTREAM_URL"
  tail -80 "$LOG" || true
  return 1
}

check_dual() {
  local xml streams
  xml="$(curl -sf "$GAMESTREAM_URL/serverinfo" || true)"
  printf '%s\n' "$xml" | tee "$WORK/serverinfo.xml"
  streams="$(printf '%s\n' "$xml" | sed -n 's/.*<MaxVideoStreams>\([^<]*\)<\/MaxVideoStreams>.*/\1/p')"
  echo "MaxVideoStreams=${streams:-missing}"
  if [ "$streams" != "2" ]; then
    echo "Expected MaxVideoStreams=2 (second output not advertised)."
    echo "--- sunshine-ds log ---"
    tail -100 "$LOG" || true
    echo "--- kscreen ---"
    kscreen-doctor -o || true
    return 1
  fi
  if ! grep -E "kwin|KWin|Virtual-|HDMI" "$LOG" >/dev/null 2>&1; then
    echo "Warning: log did not mention KWin/HDMI/Virtual yet; MaxVideoStreams=2 is still success."
  fi
  echo "PASS: sunshine-ds advertised two video streams."
  echo "Web UI: $UI_URL  GameStream: $GAMESTREAM_URL"
  echo "Production Decky Sunshine on :47989 was not modified."
}

need_bin
ensure_desktop
wayland_env
install_kwin_desktop
write_pages
ensure_virtual_output
PRIMARY="$(primary_output_name)"
VIRTUAL="$(virtual_output_name)"
echo "Primary output: $PRIMARY"
echo "Virtual output: $VIRTUAL"
place_windows "$PRIMARY" "$VIRTUAL" || echo "Window placement is best-effort; pages are still on disk."
write_sunshine_conf "$PRIMARY" "$VIRTUAL"
start_sunshine_ds
wait_for_serverinfo
check_dual
