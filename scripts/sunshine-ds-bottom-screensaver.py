#!/usr/bin/env python3
"""Idle screensaver for Game Mode headless gamescope (Moonlight bottom / :2).

Keeps damaging the virtual display so sunshine-ds-kms video/1 is not dummy
black. Withdraws when ffplay or another app owns the screen; comes back when
they leave. Window title stays sunshine-ds-kms-virtual so existing
windowkill paths still work.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

TITLE = "sunshine-ds-kms-virtual"
SKIP_NAMES = {"steamcompmgr", TITLE, ""}
SKIP_CLASSES = {"steamcompmgr"}
TREE_RE = re.compile(
    r"^\s+(0x[0-9a-f]+) \"([^\"]*)\": \(\"([^\"]*)\" \"([^\"]*)\"\)\s+(\d+)x(\d+)",
    re.I,
)


def _run(argv: list[str], env: dict[str, str] | None = None) -> str:
    try:
        out = subprocess.check_output(argv, env=env, stderr=subprocess.DEVNULL, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return ""
    return out


def parse_app_windows(tree: str) -> list[dict]:
    """Return mapped-looking clients that are not this screensaver or steamcompmgr."""
    found = []
    for line in tree.splitlines():
        m = TREE_RE.search(line)
        if not m:
            continue
        xid, name, cls, cls2, w_s, h_s = m.groups()
        w, h = int(w_s), int(h_s)
        if w < 64 or h < 64:
            continue
        if name in SKIP_NAMES or cls in SKIP_CLASSES or cls2 in SKIP_CLASSES:
            continue
        found.append(
            {
                "xid": xid,
                "name": name,
                "cls": cls,
                "w": w,
                "h": h,
            }
        )
    return found


def display_has_app(display: str) -> bool:
    env = os.environ.copy()
    env["DISPLAY"] = display
    env.pop("WAYLAND_DISPLAY", None)
    tree = _run(["xwininfo", "-root", "-tree"], env)
    if parse_app_windows(tree):
        return True
    # ffplay often has an empty title; class search still finds it.
    ff = _run(["xdotool", "search", "--class", "ffplay"], env).strip()
    return bool(ff)


def _self_test() -> int:
    tree = """
  Root window id: 0x345
     0x400009 "sunshine-ds-kms-virtual": ("tk" "Tk")  1920x1080+0+0  +0+0
     0x200001 "steamcompmgr": ()  1x1+0+0  +0+0
     0x600002 "ffplay": ("ffplay" "ffplay")  1920x1080+0+0  +0+0
     0x400001 (has no name): ()  1x1+0+0  +0+0
"""
    apps = parse_app_windows(tree)
    assert len(apps) == 1, apps
    assert apps[0]["cls"] == "ffplay"
    idle = parse_app_windows(
        '     0x400009 "sunshine-ds-kms-virtual": ("tk" "Tk")  1920x1080+0+0  +0+0\n'
        '     0x200001 "steamcompmgr": ()  1x1+0+0  +0+0\n'
    )
    assert idle == []
    print("sunshine-ds-bottom-screensaver self-test ok")
    return 0


def run_screensaver(display: str) -> int:
    os.environ["DISPLAY"] = display
    os.environ.pop("WAYLAND_DISPLAY", None)
    import tkinter as tk

    root = tk.Tk()
    root.title(TITLE)
    root.configure(bg="#07111f")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", False)

    canvas = tk.Canvas(root, highlightthickness=0, bg="#07111f")
    canvas.pack(fill="both", expand=True)

    clock = canvas.create_text(
        960, 420, text="00:00:00", fill="#e8f1ff", font=("DejaVu Sans", 96, "bold")
    )
    subtitle = canvas.create_text(
        960,
        560,
        text="Bottom stream idle",
        fill="#8fb4d9",
        font=("DejaVu Sans", 36),
    )
    hint = canvas.create_text(
        960,
        640,
        text="Moonlight GamePad  ·  no app on this screen",
        fill="#5e7f9a",
        font=("DejaVu Sans", 22),
    )
    bar = canvas.create_rectangle(0, 980, 240, 1000, fill="#3ecbff", outline="")
    state = {"x": 80, "dx": 14, "hidden": False, "t": 0}

    def layout(*_args):
        w = max(canvas.winfo_width(), 320)
        h = max(canvas.winfo_height(), 320)
        canvas.coords(clock, w / 2, h * 0.39)
        canvas.coords(subtitle, w / 2, h * 0.52)
        canvas.coords(hint, w / 2, h * 0.60)
        y0, y1 = h * 0.90, h * 0.925
        canvas.coords(bar, state["x"], y0, state["x"] + max(w * 0.18, 200), y1)

    def show():
        if not state["hidden"]:
            return
        root.deiconify()
        root.attributes("-fullscreen", True)
        root.lift()
        state["hidden"] = False
        root.update_idletasks()

    def hide():
        if state["hidden"]:
            return
        root.withdraw()
        state["hidden"] = True

    def tick():
        if display_has_app(display):
            hide()
        else:
            show()
            now = datetime.now().strftime("%H:%M:%S")
            canvas.itemconfigure(clock, text=now)
            w = max(canvas.winfo_width(), 320)
            bar_w = max(w * 0.18, 200)
            state["x"] += state["dx"]
            if state["x"] <= 40 or state["x"] >= w - bar_w - 40:
                state["dx"] *= -1
                state["x"] += state["dx"]
            layout()
        root.after(200, tick)

    canvas.bind("<Configure>", layout)
    root.after(50, tick)
    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--display", default=os.environ.get("DISPLAY", ":2"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return _self_test()
    return run_screensaver(args.display)


if __name__ == "__main__":
    raise SystemExit(main())
