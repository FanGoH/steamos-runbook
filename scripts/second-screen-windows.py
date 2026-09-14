#!/usr/bin/env python3
"""List gamescope-session windows and put one on Game Mode video/1 (:2).

X11 windows cannot hop from session gamescope (:0 / :1) onto headless :2.
Showing a :0/:1 window on the bottom stream is the same Cemu/Azahar path:
keep the source mapped, ``ffplay`` ``x11grab`` onto :2 at 1920×1080, then
``GAMESCOPECTRL_BASELAYER_WINDOW``. A window already on :2 is maximized
in place. Dual-screen Auto/On/Off is ``bind-gamepad.py set-dual-screen``.
Virtual second display On/Pause is ``~/.config/sunshine-ds-gamemode/virtual-output``
plus ``sunshine-ds-gamemode-virtual.sh --start`` / ``--stop`` (HDMI stays put).

Never ``pgrep -f`` / ``pkill -f`` sunshine. Never ``sudo systemctl --user``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def _playbook_root() -> Path:
    """Prefer the live playbook; fall back to a Decky snapshot so git checkout cannot blank QAM."""
    home = Path(os.environ.get("HOME") or "/home/deck")
    script = Path("scripts") / "second-screen-windows.py"
    candidates: list[Path] = []
    env = os.environ.get("STEAMOS_PLAYBOOK_DIR")
    if env:
        candidates.append(Path(env))
    candidates.append(home / "steamos-playbook")
    candidates.append(Path(__file__).resolve().parent.parent)
    candidates.append(home / "homebrew" / "data" / "SecondScreen")
    for cand in candidates:
        if (cand / script).is_file():
            return cand
    return candidates[0]

ROOT = _playbook_root()
BIND_PY = ROOT / "scripts" / "bind-gamepad.py"
_PAINT_CANDIDATES = (
    ROOT / "scripts" / "sunshine-ds-gamemode-virtual.sh",
    Path("/home/deck/steamos-playbook/scripts/sunshine-ds-gamemode-virtual.sh"),
)
PAINT_SH = next((p for p in _PAINT_CANDIDATES if p.is_file()), _PAINT_CANDIDATES[0])
MIRROR_PIDFILE = Path(
    os.environ.get("SECOND_SCREEN_MIRROR_PIDFILE")
    or (ROOT / "logs" / "second-screen-mirror.pid")
)
MIRROR_LOG = ROOT / "logs" / "second-screen-mirror.log"
PAD_W = 1920
PAD_H = 1080
VIRTUAL_OUTPUT_PREF = Path(
    os.environ.get("SUNSHINE_DS_VIRTUAL_OUTPUT_PREF")
    or (Path.home() / ".config" / "sunshine-ds-gamemode" / "virtual-output")
)

TREE_LINE = re.compile(
    r"^\s*(0x[0-9a-fA-F]+)\s+"
    r"(?:\"(?P<name>[^\"]*)\"|\(has no name\))"
    r":\s+\((?P<cls>[^)]*)\)\s+"
    r"(?P<w>\d+)x(?P<h>\d+)(?P<x>[+-]\d+)(?P<y>[+-]\d+)"
)
CLASS_RE = re.compile(r"\"([^\"]+)\"")
SKIP_NAMES = {
    "steamcompmgr",
    "chromium clipboard",
    "mangoapp overlay window",
    "vrstream",
}


def _playbook_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)
    uid = os.getuid()
    if uid == 0:
        uid = 1000
    env.setdefault("HOME", "/home/deck")
    env.setdefault("USER", "deck")
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
    return env


def touch_sidecar_path() -> Path:
    """Moonlight bottom taps inject here when GamePad View / Azahar Secondary is gone."""
    env = os.environ.get("SECOND_SCREEN_TOUCH_FILE")
    if env:
        return Path(env)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() or 1000}"
    if Path(runtime).name == "0":
        runtime = "/run/user/1000"
    return Path(runtime) / "second-screen-touch"


def write_touch_sidecar(display: str, wid: str) -> None:
    pad = pad_display()
    if display.rstrip(".0") == pad.rstrip(".0") or display.rstrip(".0") == "2":
        clear_touch_sidecar()
        return
    xid = wid.lower()
    if xid.isdigit():
        xid = hex(int(xid))
    if not xid.startswith("0x"):
        xid = "0x" + xid
    path = touch_sidecar_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"display={display}\nxid={xid}\n", encoding="utf-8")


def clear_touch_sidecar() -> None:
    try:
        touch_sidecar_path().unlink()
    except OSError:
        pass


def virtual_output_pref(path: Path | None = None) -> str:
    pref = path or VIRTUAL_OUTPUT_PREF
    try:
        raw = pref.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "on"
    if raw in ("off", "0", "false", "no", "pause"):
        return "off"
    return "on"


def write_virtual_output_pref(mode: str, path: Path | None = None) -> None:
    pref = path or VIRTUAL_OUTPUT_PREF
    pref.parent.mkdir(parents=True, exist_ok=True)
    pref.write_text(("off" if mode == "off" else "on") + "\n", encoding="utf-8")


def session_root_size(display: str = ":0") -> tuple[int, int]:
    try:
        proc = _run(["xdpyinfo"], timeout=2, display=display)
    except (OSError, subprocess.TimeoutExpired):
        return 0, 0
    for line in (proc.stdout or "").splitlines():
        if "dimensions:" in line:
            token = line.split()[1] if len(line.split()) > 1 else ""
            if "x" in token:
                w_s, h_s = token.split("x", 1)
                try:
                    return int(w_s), int(h_s)
                except ValueError:
                    return 0, 0
    return 0, 0


def fix_4k_scanout(display: str = ":0") -> list[str]:
    """Let native 4K HDMI scan out. Steam CEF often maps 3840×2161.

    That 1px overflow plus GAMESCOPE_COMPOSITE_FORCE flickers on a 2160
    panel. Do not touch :1 (games stay 1080p) or :2.
    """
    messages: list[str] = []
    width, height = session_root_size(display)
    if width < 2560 or height < 1440:
        return messages
    try:
        _run(
            [
                "xprop",
                "-root",
                "-f",
                "GAMESCOPE_COMPOSITE_FORCE",
                "32c",
                "-set",
                "GAMESCOPE_COMPOSITE_FORCE",
                "0",
            ],
            timeout=2,
            display=display,
        )
        messages.append("Cleared GAMESCOPE_COMPOSITE_FORCE for 4K scanout")
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        proc = _run(["xwininfo", "-root", "-tree"], timeout=3, display=display)
    except (OSError, subprocess.TimeoutExpired):
        return messages
    for win in parse_xwininfo_tree(proc.stdout or "", display):
        if int(win["width"]) != width or int(win["height"]) != height + 1:
            continue
        try:
            _run(
                ["xdotool", "windowsize", win["id"], str(width), str(height)],
                timeout=2,
                display=display,
            )
            messages.append(
                f"Clipped {win['id']} {win['width']}×{win['height']} to {width}×{height}"
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
    return messages


def sidecar_path() -> Path:
    env = os.environ.get("SUNSHINE_DS_GAMESCOPE_VIRTUAL_FILE")
    if env:
        return Path(env)
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid() or 1000}"
    if Path(runtime).name == "0":
        runtime = "/run/user/1000"
    return Path(runtime) / "sunshine-ds-gamemode-virtual"


def pad_display(text: str | None = None) -> str:
    if text is None:
        path = sidecar_path()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    for line in text.splitlines():
        if line.startswith("x11="):
            value = line.split("=", 1)[1].strip()
            if value:
                return value
    return ":2"


def session_displays(pad: str) -> list[str]:
    out: list[str] = []
    for display in (":0", ":1", pad):
        if display not in out:
            out.append(display)
    return out


def wid_decimal(wid: str) -> str:
    raw = str(wid or "").strip().lower()
    if raw.startswith("0x"):
        return str(int(raw, 16))
    return raw


def parse_class_pair(raw: str) -> tuple[str, str]:
    names = CLASS_RE.findall(raw or "")
    if len(names) >= 2:
        return names[0], names[1]
    if len(names) == 1:
        return names[0], names[0]
    return "", ""


def parse_xwininfo_tree(text: str, display: str) -> list[dict]:
    windows: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if "Root window id:" in line or "Parent window id:" in line:
            continue
        match = TREE_LINE.search(line)
        if not match:
            continue
        wid = match.group(1).lower()
        if wid in seen:
            continue
        seen.add(wid)
        name = (match.group("name") or "").strip()
        instance, cls = parse_class_pair(match.group("cls") or "")
        width = int(match.group("w"))
        height = int(match.group("h"))
        windows.append(
            {
                "id": wid,
                "display": display,
                "name": name,
                "instance": instance,
                "class": cls,
                "width": width,
                "height": height,
                "x": int(match.group("x")),
                "y": int(match.group("y")),
            }
        )
    return windows


def window_visible(win: dict) -> bool:
    name = (win.get("name") or "").strip()
    cls = (win.get("class") or "").strip()
    instance = (win.get("instance") or "").strip()
    width = int(win.get("width") or 0)
    height = int(win.get("height") or 0)
    if width <= 1 or height <= 1:
        return False
    label = name.lower()
    if label in SKIP_NAMES or cls.lower() in SKIP_NAMES or instance.lower() in SKIP_NAMES:
        return False
    if "mangoapp" in label:
        return False
    if instance.lower() == "steamwebhelper" and label != "steam big picture mode":
        return width >= 640 and height >= 360
    if not name:
        # Steam chrome children; keep only near-fullscreen surfaces.
        return width >= 800 and height >= 600
    if label in ("untitled",):
        return False
    if label == "steam" and (width < 640 or height < 360):
        return False
    if width < 80 or height < 80:
        return False
    return True


def dedupe_unnamed(windows: list[dict]) -> list[dict]:
    """Drop unnamed surfaces that match a named window on the same display."""
    named_boxes = {
        (w["display"], int(w["width"]), int(w["height"]))
        for w in windows
        if (w.get("name") or "").strip()
    }
    out: list[dict] = []
    for win in windows:
        if (win.get("name") or "").strip():
            out.append(win)
            continue
        if (win["display"], int(win["width"]), int(win["height"])) in named_boxes:
            continue
        out.append(win)
    return out


def _run(cmd: list[str], timeout: float = 3, display: str | None = None) -> subprocess.CompletedProcess:
    env = _playbook_env()
    if display:
        env["DISPLAY"] = display
        env.pop("WAYLAND_DISPLAY", None)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def list_display_windows(display: str) -> list[dict]:
    try:
        proc = _run(["xwininfo", "-root", "-tree"], timeout=3, display=display)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [w for w in parse_xwininfo_tree(proc.stdout, display) if window_visible(w)]


def list_windows(pad: str | None = None) -> list[dict]:
    target = pad or pad_display()
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for display in session_displays(target):
        for win in list_display_windows(display):
            key = (win["display"], win["id"])
            if key in seen:
                continue
            seen.add(key)
            out.append(win)
    return dedupe_unnamed(out)


def bind_json(args: list[str], timeout: int = 10) -> dict:
    if not BIND_PY.is_file():
        return {"ok": False, "message": f"Missing {BIND_PY}"}
    try:
        proc = _run(["python3", str(BIND_PY), *args], timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "bind-gamepad timed out"}
    text = (proc.stdout or "").strip()
    if not text:
        return {"ok": False, "message": (proc.stderr or "").strip() or f"exit {proc.returncode}"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": False, "message": text[:400], "rc": proc.returncode}
    if isinstance(data, dict) and "ok" not in data:
        data["ok"] = proc.returncode not in (1,)
    if isinstance(data, dict):
        data["rc"] = proc.returncode
    return data if isinstance(data, dict) else {"ok": False, "message": "bad json"}


def read_pidfile(path: Path) -> int | None:
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if pid > 1 and Path(f"/proc/{pid}").is_dir():
        return pid
    return None


def proc_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", errors="replace"
        )
    except OSError:
        return ""


def proc_display(pid: int) -> str:
    try:
        text = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return ""
    for part in text.split("\0"):
        if part.startswith("DISPLAY="):
            return part.split("=", 1)[1]
    return ""


def pids_named(comm: str) -> list[int]:
    try:
        proc = subprocess.run(
            ["pgrep", "-x", comm],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    out: list[int] = []
    for line in (proc.stdout or "").split():
        try:
            out.append(int(line))
        except ValueError:
            continue
    return out


def kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def kill_pad_x11grab(pad: str) -> None:
    wanted = {pad, f"{pad}.0", ":2", ":2.0"}
    for pid in pids_named("ffplay"):
        cmd = proc_cmdline(pid)
        if "x11grab" not in cmd:
            continue
        disp = proc_display(pid) or pad
        if disp not in wanted:
            continue
        kill_pid(pid)
    pid = read_pidfile(MIRROR_PIDFILE)
    if pid is not None:
        kill_pid(pid)
    try:
        MIRROR_PIDFILE.unlink()
    except OSError:
        pass
    clear_touch_sidecar()


def stop_pad_screensaver(pad: str) -> None:
    _run(
        ["xdotool", "search", "--name", "sunshine-ds-kms-virtual", "windowkill"],
        timeout=2,
        display=pad,
    )


def present_ffplay(pad: str, timeout_s: float = 2.5) -> str:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        proc = _run(["xdotool", "search", "--class", "ffplay"], timeout=1, display=pad)
        wids = (proc.stdout or "").split()
        if wids:
            wid = wids[-1]
            _run(
                [
                    "xdotool",
                    "windowmap",
                    wid,
                    "windowsize",
                    wid,
                    str(PAD_W),
                    str(PAD_H),
                    "windowmove",
                    wid,
                    "0",
                    "0",
                    "windowstate",
                    "--add",
                    "FULLSCREEN",
                    wid,
                    "windowstate",
                    "--add",
                    "ABOVE",
                    wid,
                    "windowfocus",
                    wid,
                    "windowactivate",
                    wid,
                    "windowraise",
                    wid,
                ],
                timeout=2,
                display=pad,
            )
            _run(
                [
                    "xprop",
                    "-root",
                    "-f",
                    "GAMESCOPECTRL_BASELAYER_WINDOW",
                    "32c",
                    "-set",
                    "GAMESCOPECTRL_BASELAYER_WINDOW",
                    wid,
                ],
                timeout=2,
                display=pad,
            )
            return wid
        time.sleep(0.2)
    return ""


def maximize_on_pad(display: str, wid: str, pad: str) -> None:
    xid = wid_decimal(wid)
    _run(["xdotool", "windowmap", xid], timeout=2, display=display)
    _run(
        [
            "xdotool",
            "windowsize",
            xid,
            str(PAD_W),
            str(PAD_H),
            "windowmove",
            xid,
            "0",
            "0",
            "windowstate",
            "--add",
            "FULLSCREEN",
            xid,
            "windowstate",
            "--add",
            "ABOVE",
            xid,
            "windowfocus",
            xid,
            "windowactivate",
            xid,
            "windowraise",
            xid,
        ],
        timeout=2,
        display=display,
    )
    if display == pad or display.rstrip(".0") == pad.rstrip(".0"):
        _run(
            [
                "xprop",
                "-root",
                "-f",
                "GAMESCOPECTRL_BASELAYER_WINDOW",
                "32c",
                "-set",
                "GAMESCOPECTRL_BASELAYER_WINDOW",
                xid,
            ],
            timeout=2,
            display=display,
        )


def start_mirror(display: str, wid: str, pad: str) -> int:
    ROOT.joinpath("logs").mkdir(parents=True, exist_ok=True)
    env = _playbook_env()
    env["DISPLAY"] = pad
    env.pop("WAYLAND_DISPLAY", None)
    env["SDL_VIDEODRIVER"] = "x11"
    env["SDL_AUDIODRIVER"] = "dummy"
    log = MIRROR_LOG.open("ab")
    proc = subprocess.Popen(
        [
            "ffplay",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-fs",
            "-noborder",
            "-alwaysontop",
            "-sn",
            "-an",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-f",
            "x11grab",
            "-window_id",
            wid_decimal(wid),
            "-framerate",
            "30",
            "-draw_mouse",
            "0",
            "-i",
            f"{display}.0",
            "-vf",
            f"scale={PAD_W}:{PAD_H}:flags=fast_bilinear",
        ],
        env=env,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    MIRROR_PIDFILE.write_text(f"{proc.pid}\n", encoding="utf-8")
    write_touch_sidecar(display, wid)
    return proc.pid


def find_window(display: str, wid: str, windows: list[dict] | None = None) -> dict | None:
    needle = wid.lower()
    if needle.isdigit():
        needle = hex(int(needle))
    if not needle.startswith("0x"):
        needle = "0x" + needle
    pad = pad_display()
    pool = windows if windows is not None else list_windows(pad)
    for win in pool:
        if win["id"] == needle and (not display or win["display"] == display):
            return win
    for win in pool:
        if win["id"] == needle:
            return win
    return None


def current_mirror(pad: str) -> dict:
    pid = read_pidfile(MIRROR_PIDFILE)
    if pid is None:
        return {"running": False, "pid": None, "cmd": ""}
    return {"running": True, "pid": pid, "cmd": proc_cmdline(pid)[:220], "display": pad}


def status_payload() -> dict:
    pad = pad_display()
    live = bind_json(["second-screen-streaming"])
    windows = list_windows(pad)
    clients = live.get("clients") if isinstance(live.get("clients"), list) else []
    sidecar = sidecar_path()
    return {
        "ok": True,
        "pad_display": pad,
        "sidecar": sidecar.is_file(),
        "virtual_output": virtual_output_pref(),
        "virtual_output_live": sidecar.is_file(),
        "dual_screen": live.get("mode") or "auto",
        "dual_screen_live": live,
        "clients": clients,
        "mirror": current_mirror(pad),
        "windows": windows,
    }


def cmd_status(_args: argparse.Namespace) -> int:
    json.dump(status_payload(), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    payload = status_payload()
    json.dump({"ok": True, "windows": payload["windows"], "pad_display": payload["pad_display"]}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_set_dual_screen(args: argparse.Namespace) -> int:
    data = bind_json(["set-dual-screen", "--mode", args.mode])
    json.dump(data, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0 if data.get("ok") is not False else 1


def cmd_set_virtual_output(args: argparse.Namespace) -> int:
    mode = "off" if args.mode == "off" else "on"
    write_virtual_output_pref(mode)
    if not PAINT_SH.is_file():
        payload = status_payload()
        payload["ok"] = False
        payload["message"] = f"Missing {PAINT_SH}"
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1
    flag = "--stop" if mode == "off" else "--start"
    try:
        proc = _run(["bash", str(PAINT_SH), flag], timeout=30)
    except subprocess.TimeoutExpired:
        payload = status_payload()
        payload["ok"] = False
        payload["message"] = f"virtual output {flag} timed out"
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1
    payload = status_payload()
    err = (proc.stderr or "").strip()
    if mode == "off":
        extra = fix_4k_scanout(":0")
        payload["messages"] = ["Paused the virtual second display. HDMI is unchanged."]
        payload["messages"].extend(extra)
    else:
        payload["messages"] = ["Virtual second display on (:2 / Moonlight bottom)."]
    if proc.returncode not in (0, None) and err:
        payload["ok"] = False
        payload["message"] = err[:400]
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    pad = pad_display()
    win = find_window(args.display or "", args.window_id)
    if win is None:
        json.dump({"ok": False, "message": f"No window {args.window_id} on {args.display or 'session'}"}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    display = win["display"]
    wid = win["id"]
    on_pad = display.rstrip(".0") == pad.rstrip(".0")
    is_saver = "sunshine-ds-kms-virtual" in (win.get("name") or "") or (
        (win.get("class") or "").lower() == "tk"
    )
    kill_pad_x11grab(pad)
    if not is_saver:
        stop_pad_screensaver(pad)
    if on_pad:
        if is_saver:
            xid = wid_decimal(wid)
            _run(
                ["xdotool", "windowmap", xid, "windowraise", xid],
                timeout=2,
                display=display,
            )
            _run(
                [
                    "xprop",
                    "-root",
                    "-f",
                    "GAMESCOPECTRL_BASELAYER_WINDOW",
                    "32c",
                    "-set",
                    "GAMESCOPECTRL_BASELAYER_WINDOW",
                    xid,
                ],
                timeout=2,
                display=display,
            )
            payload = status_payload()
            payload["messages"] = [f"Raised {win.get('name') or wid} on {pad}"]
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
            return 0
        maximize_on_pad(display, wid, pad)
        payload = status_payload()
        payload["messages"] = [f"Maximized {win.get('name') or wid} on {pad}"]
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0
    _run(["xdotool", "windowmap", wid_decimal(wid)], timeout=2, display=display)
    pid = start_mirror(display, wid, pad)
    ff = present_ffplay(pad)
    payload = status_payload()
    payload["messages"] = [
        f"Showing {win.get('name') or wid} from {display} on {pad}"
        + ("" if ff else " (ffplay window not mapped yet)")
    ]
    payload["mirror"]["pid"] = pid
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_idle(_args: argparse.Namespace) -> int:
    pad = pad_display()
    kill_pad_x11grab(pad)
    time.sleep(0.3)
    if not PAINT_SH.is_file():
        json.dump({"ok": False, "message": f"Missing {PAINT_SH}"}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    try:
        proc = _run(["bash", str(PAINT_SH), "--paint"], timeout=20)
    except subprocess.TimeoutExpired:
        json.dump({"ok": False, "message": "idle clock --paint timed out"}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    payload = status_payload()
    err = (proc.stderr or "").strip()
    payload["messages"] = ["Restored Moonlight Screensaver on the second screen"]
    if proc.returncode not in (0, None) and err:
        payload["ok"] = False
        payload["message"] = err[:400]
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


SAMPLE_TREE = """
xwininfo: Window id: 0x34f (the root window) (has no name)

  Root window id: 0x34f (the root window) (has no name)
  Parent window id: 0x0 (none)
     16 children:
     0x2200035 "Steam Big Picture Mode": ("steamwebhelper" "steam")  1920x1080+0+0  +0+0
        4 children:
        0x1c0001a (has no name): ()  410x103+0+0  +0+0
        0x1c00018 (has no name): ()  1x1+0+0  +0+0
     0xa00041 "VRStream": ("steam" "steam")  32x32+944+524  +944+524
     0x200007 "mangoapp overlay window": ("mangoapp overlay window" "mangoapp overlay window")  1920x1080+0+0  +0+0
     0x200001 "steamcompmgr": ()  1x1+0+0  +0+0
     0x400015 "sunshine-ds-kms-virtual": ("tk" "Tk")  1920x1080+0+0  +0+0
     0x60000a "GamePad View": ("Cemu" "Cemu")  854x480+0+0  +0+0
"""


def self_test() -> int:
    parsed = parse_xwininfo_tree(SAMPLE_TREE, ":0")
    by_id = {w["id"]: w for w in parsed}
    assert "0x2200035" in by_id
    assert by_id["0x2200035"]["name"] == "Steam Big Picture Mode"
    assert by_id["0x2200035"]["class"] == "steam"
    assert window_visible(by_id["0x2200035"]) is True
    assert window_visible(by_id["0xa00041"]) is False
    assert window_visible(by_id["0x200007"]) is False
    assert window_visible(by_id["0x200001"]) is False
    assert window_visible(by_id["0x1c00018"]) is False
    assert window_visible(by_id["0x1c0001a"]) is False
    assert window_visible(by_id["0x400015"]) is True
    assert window_visible(by_id["0x60000a"]) is True
    cleaned = dedupe_unnamed([w for w in parsed if window_visible(w)])
    assert [w["name"] for w in cleaned] == [
        "Steam Big Picture Mode",
        "sunshine-ds-kms-virtual",
        "GamePad View",
    ]
    tall = parse_xwininfo_tree(
        '     0x1800016 (has no name): ()  3840x2161+0+0  +0+0\n',
        ":0",
    )
    assert tall and tall[0]["width"] == 3840 and tall[0]["height"] == 2161
    assert pad_display("serial=92\npw_node=89\nx11=:2\n") == ":2"
    assert session_displays(":2") == [":0", ":1", ":2"]
    with tempfile.TemporaryDirectory() as td:
        pref = Path(td) / "virtual-output"
        assert virtual_output_pref(pref) == "on"
        write_virtual_output_pref("off", pref)
        assert virtual_output_pref(pref) == "off"
        write_virtual_output_pref("on", pref)
        assert virtual_output_pref(pref) == "on"
    with tempfile.TemporaryDirectory() as td:
        os.environ["SECOND_SCREEN_TOUCH_FILE"] = str(Path(td) / "second-screen-touch")
        os.environ["SUNSHINE_DS_GAMESCOPE_VIRTUAL_FILE"] = str(Path(td) / "virtual")
        Path(os.environ["SUNSHINE_DS_GAMESCOPE_VIRTUAL_FILE"]).write_text(
            "x11=:2\n", encoding="utf-8"
        )
        write_touch_sidecar(":0", "0x60000a")
        text = touch_sidecar_path().read_text(encoding="utf-8")
        assert "display=:0" in text
        assert "xid=0x60000a" in text
        write_touch_sidecar(":2", "0x400015")
        assert not touch_sidecar_path().is_file()
        os.environ.pop("SECOND_SCREEN_TOUCH_FILE", None)
        os.environ.pop("SUNSHINE_DS_GAMESCOPE_VIRTUAL_FILE", None)
    assert wid_decimal("0x2200035") == str(int("0x2200035", 16))
    assert wid_decimal("35717173") == "35717173"
    visible = [w for w in parsed if window_visible(w)]
    names = {w["name"] for w in visible}
    assert "Steam Big Picture Mode" in names
    assert "GamePad View" in names
    assert "mangoapp overlay window" not in names
    print("second-screen-windows self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("list").set_defaults(func=cmd_list)
    p_ds = sub.add_parser("set-dual-screen")
    p_ds.add_argument("--mode", required=True, choices=("auto", "on", "off"))
    p_ds.set_defaults(func=cmd_set_dual_screen)
    p_vo = sub.add_parser("set-virtual-output")
    p_vo.add_argument("--mode", required=True, choices=("on", "off"))
    p_vo.set_defaults(func=cmd_set_virtual_output)
    p_show = sub.add_parser("show")
    p_show.add_argument("--display", default="")
    p_show.add_argument("--id", dest="window_id", required=True)
    p_show.set_defaults(func=cmd_show)
    sub.add_parser("idle").set_defaults(func=cmd_idle)
    sub.add_parser("fix-4k-scanout").set_defaults(
        func=lambda _a: (
            json.dump({"ok": True, "messages": fix_4k_scanout(":0")}, sys.stdout, indent=2)
            or sys.stdout.write("\n")
            or 0
        )
    )
    sub.add_parser("self-test").set_defaults(func=lambda _a: self_test())
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
