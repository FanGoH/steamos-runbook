#!/usr/bin/env python3
"""Pick a 3DS dump for standalone Azahar. Prints the path on stdout.

Moonlight Open used to sit on a pad-wait and then Azahar's library scan.
This list is meant to appear on HDMI immediately so a title can be chosen
while ini/bind prep runs in the background.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

EXTS = {".3ds", ".cci", ".cxi", ".cia", ".3dsx", ".app", ".ncch"}
SKIP_DIR_NAMES = {"games", "3ds", "n3ds", "roms", "miscfiles"}


def root_has_games(root: Path) -> bool:
    if not root.is_dir():
        return False
    for ext in EXTS:
        if next(root.glob(f"*{ext}"), None) or next(root.glob(f"*{ext.upper()}"), None):
            return True
        if any(child.is_dir() and (next(child.glob(f"*{ext}"), None) or next(child.glob(f"*{ext.upper()}"), None)) for child in root.iterdir()):
            return True
    return False


def default_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    env_dir = os.environ.get("AZAHAR_GAMES_DIR", "").strip()
    extra = os.environ.get("AZAHAR_GAMES_EXTRA_DIRS", "").strip()
    if env_dir:
        roots.append(Path(env_dir).expanduser())
    else:
        roots.append(home / "emulation/3ds/games")
    if extra:
        roots.extend(Path(part).expanduser() for part in extra.split() if part.strip())
    if not any(root_has_games(root) for root in roots):
        fallback = home / "retrodeck/roms/n3ds"
        if fallback.is_dir():
            roots.append(fallback)
    return roots


def clean_stem(stem: str) -> str:
    for token in (
        " (USA)",
        " (Japan)",
        " (Europe)",
        " (Rev 1)",
        " (Rev 2)",
        " (Rev 3)",
        " (En,Fr,Es)",
        " (En,Ja,Fr,De,Es,It,Zh,Ko)",
        " (En,Ja,Fr,De,Es,It,Ko)",
    ):
        stem = stem.replace(token, "")
    return stem.strip()


def display_title(path: Path) -> str:
    parent = path.parent.name
    if parent and parent.lower() not in SKIP_DIR_NAMES and " " in parent:
        return parent.replace("_", " ")
    cleaned = clean_stem(path.stem)
    if cleaned:
        return cleaned
    if parent and parent.lower() not in SKIP_DIR_NAMES:
        return parent.replace("_", " ")
    return path.name


def collect_games(roots: list[Path]) -> list[tuple[str, Path]]:
    by_title: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        files: list[Path] = []
        for ext in EXTS:
            files.extend(root.glob(f"*{ext}"))
            files.extend(root.glob(f"*{ext.upper()}"))
        for child in sorted(root.iterdir() if root.is_dir() else []):
            if not child.is_dir():
                continue
            folder_files: list[Path] = []
            for ext in EXTS:
                folder_files.extend(child.glob(f"*{ext}"))
                folder_files.extend(child.glob(f"*{ext.upper()}"))
            if folder_files:
                files.append(max(folder_files, key=lambda p: p.stat().st_size))
        for path in files:
            if not path.is_file():
                continue
            title = display_title(path)
            prev = by_title.get(title)
            if prev is None or path.stat().st_size > prev.stat().st_size:
                by_title[title] = path.resolve()
    return sorted(by_title.items(), key=lambda item: item[0].casefold())


def kwin_fill_hdmi(title: str) -> None:
    output = os.environ.get("CEMU_TV_OUTPUT", "HDMI-A-1")
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    js_path = runtime / "place-azahar-picker.js"
    js_path.write_text(
        f"""
function screenGeom(name) {{
    for (const s of workspace.screens) {{
        if (s.name === name) {{
            const g = s.geometry;
            return {{ x: g.x, y: g.y, width: g.width, height: g.height, screen: s }};
        }}
    }}
    return null;
}}
const tv = screenGeom("{output}");
if (tv) {{
    for (const w of workspace.windowList()) {{
        if (String(w.caption || "") !== "{title}") continue;
        try {{ w.minimized = false; }} catch (e) {{}}
        try {{ w.keepAbove = true; }} catch (e) {{}}
        try {{ w.noBorder = true; }} catch (e) {{}}
        try {{ w.output = tv.screen; }} catch (e) {{}}
        try {{ w.frameGeometry = {{ x: tv.x, y: tv.y, width: tv.width, height: tv.height }}; }} catch (e) {{}}
    }}
}}
""",
        encoding="utf-8",
    )
    plugin = "place-azahar-picker-once"
    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    for args in (
        ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", plugin],
        ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", str(js_path), plugin],
        ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "start"],
        ["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", plugin],
    ):
        subprocess.run(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def pick_with_tk(games: list[tuple[str, Path]]) -> Path | None:
    import tkinter as tk

    chosen: dict[str, Path | None] = {"path": None}
    title = "Azahar games"
    root = tk.Tk()
    root.title(title)
    root.configure(bg="#111111")
    root.geometry("1920x1080+0+0")
    try:
        root.attributes("-fullscreen", True)
    except tk.TclError:
        pass
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass

    header = tk.Frame(root, bg="#111111")
    header.pack(fill="x", padx=40, pady=(36, 12))
    tk.Label(
        header,
        text="3DS",
        fg="#ffffff",
        bg="#111111",
        font=("Noto Sans", 32, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        header,
        text="Pick a game. Azahar is getting ready in the background.",
        fg="#bbbbbb",
        bg="#111111",
        font=("Noto Sans", 16),
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    canvas = tk.Canvas(root, bg="#111111", highlightthickness=0)
    scroll = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True, padx=(40, 0), pady=(0, 40))
    inner = tk.Frame(canvas, bg="#111111")
    canvas.create_window((0, 0), window=inner, anchor="nw")

    def finish(path: Path | None) -> None:
        chosen["path"] = path
        root.destroy()

    buttons: list[tk.Button] = []

    def select_index(idx: int) -> None:
        if not buttons:
            return
        idx = max(0, min(idx, len(buttons) - 1))
        for i, btn in enumerate(buttons):
            if i == idx:
                btn.configure(bg="#3d5afe", fg="#ffffff", activebackground="#3d5afe")
                btn.focus_set()
            else:
                btn.configure(bg="#1c1c1c", fg="#eeeeee", activebackground="#2a2a2a")

    def on_click(idx: int, path: Path) -> None:
        select_index(idx)
        finish(path)

    for i, (name, path) in enumerate(games):
        btn = tk.Button(
            inner,
            text=name,
            font=("Noto Sans", 22),
            anchor="w",
            padx=24,
            pady=18,
            bd=0,
            highlightthickness=0,
            bg="#1c1c1c",
            fg="#eeeeee",
            activebackground="#2a2a2a",
            activeforeground="#ffffff",
            command=lambda idx=i, p=path: on_click(idx, p),
        )
        btn.pack(fill="x", pady=6, padx=(0, 24))
        buttons.append(btn)

    def on_keys(event: tk.Event) -> str | None:
        if event.keysym in ("Escape", "q"):
            finish(None)
            return "break"
        focused = root.focus_get()
        try:
            idx = buttons.index(focused) if focused in buttons else 0
        except ValueError:
            idx = 0
        if event.keysym in ("Down", "j", "s"):
            select_index(idx + 1)
            return "break"
        if event.keysym in ("Up", "k", "w"):
            select_index(idx - 1)
            return "break"
        if event.keysym in ("Return", "space", "KP_Enter"):
            if 0 <= idx < len(games):
                finish(games[idx][1])
            return "break"
        return None

    def on_mousewheel(event: tk.Event) -> None:
        delta = -1 if event.delta > 0 or event.num == 4 else 1
        canvas.yview_scroll(delta, "units")

    inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    root.bind("<Key>", on_keys)
    root.bind("<Button-4>", on_mousewheel)
    root.bind("<Button-5>", on_mousewheel)
    root.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    if buttons:
        select_index(0)
    root.after(150, lambda: kwin_fill_hdmi(title))
    root.after(400, lambda: kwin_fill_hdmi(title))
    root.mainloop()
    return chosen["path"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pick a 3DS dump for Azahar Dual-Screen")
    parser.add_argument("--list", action="store_true", help="Print titles and paths, no UI")
    args = parser.parse_args(argv)
    games = collect_games(default_roots())
    if args.list:
        if not games:
            print("No 3DS dumps found", file=sys.stderr)
            return 3
        for title, path in games:
            print(f"{title}\t{path}")
        return 0
    if not games:
        print("No 3DS dumps found in AZAHAR_GAMES_DIR", file=sys.stderr)
        return 3
    os.environ.setdefault("DISPLAY", ":0")
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    try:
        picked = pick_with_tk(games)
    except Exception as exc:
        print(f"Azahar picker UI failed: {exc}", file=sys.stderr)
        return 1
    if picked is None:
        return 2
    print(picked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
