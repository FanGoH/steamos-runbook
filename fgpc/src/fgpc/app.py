"""fgpc — FanGoH Gaming PC CLI (Typer + Rich)."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from typing import Optional

import typer
from rich.table import Table

from fgpc import __version__
from fgpc.catalog import EXAMPLES, GROUPS, TIPS, TOPIC_HELP
from fgpc.invoke import Result, run, run_root
from fgpc.menu import pick
from fgpc.playbook import playbook_root, scripts
from fgpc.pretty import banner, console, err, kv_table, ok, show_result, warn

app = typer.Typer(
    name="fgpc",
    help="FanGoH Gaming PC — pretty CLI for this Steam Machine playbook.",
    no_args_is_help=False,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
    add_completion=True,
)

host_app = typer.Typer(help="Bootstrap, post-update, health.")
mode_app = typer.Typer(help="Plasma Desktop DS vs Game Mode.")
stream_app = typer.Typer(help="Moonlight sunshine-ds :48100 / :48200.")
screen_app = typer.Typer(help="Second screen, windows, idle clock.")
pad_app = typer.Typer(help="EmuPads mux and emulator binds.")
hide_app = typer.Typer(help="Kernel-unplug extra pads (NMH3).")
emu_app = typer.Typer(help="Eden / Azahar / Cemu quick graphics.")
decky_app = typer.Typer(help="Install or reload Decky plugins.")
saves_app = typer.Typer(help="Syncthing Eden / Azahar save mesh.")

app.add_typer(host_app, name="host")
app.add_typer(mode_app, name="mode")
app.add_typer(stream_app, name="stream")
app.add_typer(screen_app, name="screen")
app.add_typer(pad_app, name="pad")
app.add_typer(hide_app, name="hide")
app.add_typer(emu_app, name="emu")
app.add_typer(decky_app, name="decky")
app.add_typer(saves_app, name="saves")

DECKY = {
    "pads": ("Emu Pads", "ensure-emu-pads-decky.sh"),
    "hide": ("Pad Hide", "ensure-pad-hide-decky.sh"),
    "screen": ("Second Screen", "ensure-second-screen-decky.sh"),
    "quick": ("Emu Quick", "ensure-emu-quick-decky.sh"),
    "sunshine": ("Sunshine DS", "ensure-sunshine-ds-decky.sh"),
    "playbook": ("Playbook", "ensure-playbook-decky.sh"),
    "tailscale": ("Tailscale Control", "ensure-tailscale-control.sh"),
}


def _emit(result: Result, *, ok_msg: str = "") -> None:
    if result.stderr and result.data is None:
        warn(result.stderr.strip()[:400])
    show_result(result.data, result.stdout, result.stderr if result.data else "")
    if result.rc == 0 and ok_msg:
        ok(ok_msg)
    if result.rc not in (0, 2):
        raise typer.Exit(result.rc)
    if result.rc == 2:
        raise typer.Exit(2)


def _home() -> None:
    banner()
    table = Table(box=None, show_header=True, expand=True)
    table.add_column("group", style="cyan", no_wrap=True)
    table.add_column("what")
    for name, blurb in GROUPS:
        table.add_row(name, blurb)
    console.print(table)
    console.print()
    console.print("[bold]examples[/bold]")
    for cmd, why in EXAMPLES[:8]:
        console.print(f"  [green]{cmd:<42}[/green] [dim]{why}[/dim]")
    console.print()
    console.print(
        "[dim]fgpc <group> --help · fgpc examples · fgpc tips · "
        "fgpc complete install · arrows: fgpc menu[/dim]"
    )


def _dispatch_line(line: str) -> None:
    parts = shlex.split(line)
    if parts and parts[0] == "fgpc":
        parts = parts[1:]
    os.execvp(sys.argv[0], ["fgpc", *parts])


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", help="Print fgpc version."),
) -> None:
    if version:
        console.print(f"fgpc {__version__}  playbook {playbook_root()}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _home()


@app.command("menu")
def menu_cmd() -> None:
    """Arrow menu of common commands (SSH-safe)."""
    choices = [(f"{cmd}  — {why}", cmd) for cmd, why in EXAMPLES]
    chosen = pick("fgpc menu", choices)
    if not chosen:
        raise typer.Exit(0)
    console.print(f"[dim]$ {chosen}[/dim]")
    _dispatch_line(chosen)


@app.command("examples")
def examples_cmd() -> None:
    """Copy-paste command examples."""
    table = Table(title="fgpc examples", show_lines=False)
    table.add_column("command", style="green")
    table.add_column("why")
    for cmd, why in EXAMPLES:
        table.add_row(cmd, why)
    console.print(table)


@app.command("tips")
def tips_cmd() -> None:
    """Do-not-rediscover rules for this box."""
    banner()
    for i, tip in enumerate(TIPS, 1):
        console.print(f"  [cyan]{i:2d}.[/cyan] {tip}")


@app.command("help")
def help_cmd(
    topic: Optional[str] = typer.Argument(None, help="Group name (pad, hide, stream, …)"),
) -> None:
    """Topic help with examples. Same as fgpc <group> --help plus recipes."""
    if not topic:
        _home()
        return
    text = TOPIC_HELP.get(topic)
    if not text:
        err(f"unknown topic {topic}. try: {', '.join(TOPIC_HELP)}")
        raise typer.Exit(2)
    console.print(text)


@app.command("complete")
def complete_cmd(
    action: str = typer.Argument(
        "show",
        help="show | install | bash | zsh",
    ),
) -> None:
    """Shell autocomplete (Typer / Click)."""
    prog = "fgpc"
    if action == "install":
        console.print("Run one of:")
        console.print("  [green]fgpc --install-completion bash[/green]")
        console.print("  [green]fgpc --install-completion zsh[/green]")
        console.print("Then restart the shell. Or add to ~/.bashrc:")
        console.print('  [green]eval "$(fgpc --show-completion bash)"[/green]')
        return
    shell = "bash" if action in ("show", "bash") else action
    if shell not in ("bash", "zsh", "fish"):
        err("shell must be bash, zsh, or fish")
        raise typer.Exit(2)
    # Re-exec so Click writes the completion script
    os.execvp(sys.argv[0], [prog, "--show-completion", shell])


@app.command("self-test")
def self_test() -> None:
    """Offline CLI checks (no kernel hide, no Steam)."""
    root = playbook_root()
    assert (root / "scripts" / "bind-gamepad.py").is_file()
    from typer.testing import CliRunner

    runner = CliRunner()
    help_rc = runner.invoke(app, ["--help"])
    assert help_rc.exit_code == 0, help_rc.output
    for group in ("host", "mode", "stream", "screen", "pad", "hide", "emu", "decky", "saves"):
        got = runner.invoke(app, [group, "--help"])
        assert got.exit_code == 0, f"{group}: {got.output}"
    hide = scripts() / "hide-controllers.py"
    if hide.is_file():
        result = run("hide-controllers.py", ["self-test"], json_out=False, timeout=20)
        if result.rc != 0:
            err(result.stderr or result.stdout)
            raise typer.Exit(1)
    ok(f"fgpc self-test ok  playbook={root}")


# --- host ---


@host_app.command("status")
def host_status() -> None:
    """Light status: playbook paths, mux, kms, pad-hide sudo."""
    rows = [("playbook", str(playbook_root())), ("user", os.environ.get("USER", ""))]
    mux = run("bind-gamepad.py", ["status"], timeout=15)
    if isinstance(mux.data, dict):
        m = mux.data.get("mux") or {}
        rows.append(("mux", f"running={m.get('running')} mode={m.get('mode')}"))
        rows.append(("pads", str(len(mux.data.get("pads") or []))))
    kms = run("ensure-sunshine-ds-gamemode.sh", ["--status"], json_out=False, timeout=20)
    rows.append(("kms", (kms.stdout or kms.stderr or "").strip().splitlines()[-1] if (kms.stdout or kms.stderr) else f"rc={kms.rc}"))
    hide = run("hide-controllers.py", ["list"], timeout=12)
    if isinstance(hide.data, dict):
        rows.append(("hide sudo", str(hide.data.get("sudo"))))
        rows.append(("hide pads", str(len(hide.data.get("pads") or []))))
    kv_table("host", rows)


@host_app.command("health")
def host_health() -> None:
    """Full ./health-check.sh (streamed)."""
    result = run_root("health-check.sh", stream=True, timeout=180)
    raise typer.Exit(result.rc)


@host_app.command("post-update")
def host_post_update() -> None:
    """./post-update.sh after a SteamOS update."""
    result = run_root("post-update.sh", stream=True, timeout=600)
    raise typer.Exit(result.rc)


@host_app.command("bootstrap")
def host_bootstrap() -> None:
    """./bootstrap.sh on a fresh box."""
    result = run_root("bootstrap.sh", stream=True, timeout=600)
    raise typer.Exit(result.rc)


# --- mode ---


@mode_app.command("status")
def mode_status() -> None:
    """Desktop DS + Game Mode kms one-liners."""
    desk = run("ensure-sunshine-ds.sh", ["--status"], json_out=False, timeout=20)
    kms = run("ensure-sunshine-ds-gamemode.sh", ["--status"], json_out=False, timeout=20)
    console.print("[bold]desktop :48100[/bold]")
    console.print((desk.stdout or desk.stderr or "").rstrip() or f"rc={desk.rc}")
    console.print("[bold]gamemode :48200[/bold]")
    console.print((kms.stdout or kms.stderr or "").rstrip() or f"rc={kms.rc}")


@mode_app.command("desktop")
def mode_desktop() -> None:
    """Start Plasma dual-stream DS (:48100)."""
    result = run("ensure-sunshine-ds.sh", json_out=False, timeout=90, stream=True)
    raise typer.Exit(result.rc)


@mode_app.command("game")
def mode_game() -> None:
    """Stop desktop DS and switch to Game Mode."""
    result = run("switch-to-game-mode.sh", json_out=False, timeout=60, stream=True)
    raise typer.Exit(result.rc)


# --- stream ---


@stream_app.command("status")
def stream_status() -> None:
    """Desktop :48100 and Game Mode :48200."""
    mode_status()


@stream_app.command("desktop")
def stream_desktop(
    action: str = typer.Argument("status", help="status | start | stop | restart"),
    force: bool = typer.Option(False, "--force", help="Restart even if BUSY."),
) -> None:
    """Desktop sunshine-ds :48100 (Distrobox). Not Decky :47989."""
    args = {
        "status": ["--status"],
        "start": [],
        "stop": ["--stop"],
        "restart": ["--restart"] + (["--force"] if force else []),
    }.get(action)
    if args is None:
        err("action: status | start | stop | restart")
        raise typer.Exit(2)
    result = run("ensure-sunshine-ds.sh", args, json_out=False, timeout=90, stream=True)
    raise typer.Exit(result.rc)


@stream_app.command("gamemode")
def stream_gamemode(
    action: str = typer.Argument("status", help="status | start | start-kms | stop | paint"),
) -> None:
    """Game Mode kms :48200. Use start-kms when :2 is already up."""
    if action == "paint":
        result = run(
            "sunshine-ds-gamemode-virtual.sh",
            ["--paint"],
            json_out=False,
            timeout=40,
            stream=True,
        )
        raise typer.Exit(result.rc)
    args = {
        "status": ["--status"],
        "start": ["--start"],
        "start-kms": ["--start-kms"],
        "stop": ["--stop"],
    }.get(action)
    if args is None:
        err("action: status | start | start-kms | stop | paint")
        raise typer.Exit(2)
    result = run("ensure-sunshine-ds-gamemode.sh", args, json_out=False, timeout=90, stream=True)
    raise typer.Exit(result.rc)


@stream_app.command("close")
def stream_close(
    target: str = typer.Argument(..., help="cemu | azahar"),
) -> None:
    """Moonlight Quit leftover: stop Cemu or Azahar."""
    if target not in ("cemu", "azahar"):
        err("cemu or azahar")
        raise typer.Exit(2)
    result = run("sunshine-app-stop.sh", [target], json_out=False, timeout=20)
    _emit(result, ok_msg=f"stopped {target}")


# --- screen ---


@screen_app.command("status")
def screen_status() -> None:
    """Second Screen JSON (windows + dual-screen)."""
    _emit(run("second-screen-windows.py", ["status"], timeout=15))


@screen_app.command("list")
def screen_list() -> None:
    """gamescope windows on :0 / :1 / :2."""
    _emit(run("second-screen-windows.py", ["list"], timeout=15))


@screen_app.command("dual")
def screen_dual(
    mode: str = typer.Argument(..., help="auto | on | off"),
) -> None:
    """Tender dual-screen Auto / Dual-screen / HDMI only."""
    if mode not in ("auto", "on", "off"):
        err("auto | on | off")
        raise typer.Exit(2)
    _emit(run("second-screen-windows.py", ["set-dual-screen", "--mode", mode]))


@screen_app.command("show")
def screen_show(
    window_id: str = typer.Option(..., "--id", help="X11 window id"),
    display: str = typer.Option("", "--display", help=":0 :1 or :2"),
) -> None:
    """Put a window on the Moonlight bottom stream."""
    args = ["show", "--id", window_id]
    if display:
        args.extend(["--display", display])
    _emit(run("second-screen-windows.py", args, timeout=25))


@screen_app.command("clock")
def screen_clock() -> None:
    """Idle screensaver clock on :2."""
    _emit(run("second-screen-windows.py", ["idle"], timeout=25))


# --- pad ---


@pad_app.command("list")
def pad_list() -> None:
    """Host joysticks (JSON table)."""
    _emit(run("bind-gamepad.py", ["list"], timeout=12))


@pad_app.command("status")
def pad_status() -> None:
    """Pads + mux + Cemu/Azahar/Eden binds."""
    _emit(run("bind-gamepad.py", ["status"], timeout=15))


@pad_app.command("mode")
def pad_mode(
    mode: str = typer.Argument(..., help="shared | multi"),
) -> None:
    """Shared P1 (last pad wins) or multi P1+P2."""
    if mode not in ("shared", "multi"):
        err("shared | multi")
        raise typer.Exit(2)
    _emit(run("bind-gamepad.py", ["set-mode", "--mode", mode]))


@pad_app.command("apply")
def pad_apply(
    emu: str = typer.Option("all", "--emu", help="all | cemu | azahar | eden"),
    mode: str = typer.Option("", "--mode", help="shared | multi"),
    pads: str = typer.Option("", "--pads", help="jsN,jsM or names"),
    cemu_p1: str = typer.Option("", "--cemu-p1", help="gamepad | pro"),
    restart: bool = typer.Option(False, "--restart"),
) -> None:
    """Bind emulators to EmuPads sinks."""
    args = ["apply", "--emu", emu, "--force", "--all-sources"]
    if mode:
        args.extend(["--mode", mode])
    if pads:
        args.extend(["--pads", pads])
        args.remove("--all-sources")
    if cemu_p1:
        args.extend(["--cemu-p1", cemu_p1])
    if restart:
        args.append("--restart")
    _emit(run("bind-gamepad.py", args, timeout=55 if restart else 25))


@pad_app.command("bind")
def pad_bind(
    emu: str = typer.Argument(..., help="cemu | azahar | eden"),
    match: str = typer.Option("", "--match", help="Thor, Odin, …"),
    cemu_p1: str = typer.Option("", "--cemu-p1", help="gamepad | pro"),
) -> None:
    """Bind one emulator (still via bind-gamepad.py)."""
    if emu not in ("cemu", "azahar", "eden"):
        err("cemu | azahar | eden")
        raise typer.Exit(2)
    args = [emu, "--all-sources"]
    if match:
        args.extend(["--match", match])
    if cemu_p1:
        args.extend(["--cemu-p1", cemu_p1])
    _emit(run("bind-gamepad.py", args, timeout=25))


@pad_app.command("mux")
def pad_mux() -> None:
    """Ensure emupads-mux.service is up."""
    result = run("ensure-emupads-mux.sh", json_out=False, timeout=40, stream=True)
    raise typer.Exit(result.rc)


# --- hide ---


@hide_app.command("list")
def hide_list() -> None:
    """Pads + hidden + UI-pad lock."""
    _emit(run("hide-controllers.py", ["list"], timeout=12))


@hide_app.command("off")
def hide_off(
    pad_id: str = typer.Argument(..., help="id from fgpc hide list"),
    force: bool = typer.Option(False, "--force", help="SSH only; hide the UI pad"),
) -> None:
    """Look unplugged (USB authorized=0 / HID unbind)."""
    args = ["hide", "--id", pad_id]
    if force:
        args.append("--force")
    _emit(run("hide-controllers.py", args, timeout=12))


@hide_app.command("on")
def hide_on(
    pad_id: str = typer.Argument(..., help="id from fgpc hide list"),
) -> None:
    """Plug the pad back in to the OS."""
    _emit(run("hide-controllers.py", ["show", "--id", pad_id], timeout=12))


@hide_app.command("apply")
def hide_apply() -> None:
    """Re-apply ~/.config/pad-hide/hidden.json."""
    _emit(run("hide-controllers.py", ["apply"], timeout=15))


# --- emu ---


@emu_app.command("status")
def emu_status(
    emu: str = typer.Option("", "--emu", help="eden | azahar | cemu"),
    title: str = typer.Option("", "--title", help="title id"),
) -> None:
    """Emu Quick rows."""
    args = ["status"]
    if emu:
        args.extend(["--emu", emu])
    if title:
        args.extend(["--title", title])
    _emit(run("emu-quick-settings.py", args, timeout=15))


@emu_app.command("set")
def emu_set(
    emu: str = typer.Option(..., "--emu", help="eden | azahar | cemu"),
    key: str = typer.Option(..., "--key"),
    value: str = typer.Option(..., "--value"),
    scope: str = typer.Option("global", "--scope"),
    title: str = typer.Option("", "--title"),
    live: bool = typer.Option(False, "--live", help="Eden hotkeys only"),
) -> None:
    """Set one quick-settings key."""
    args = ["set", "--emu", emu, "--key", key, "--value", value, "--scope", scope]
    if title:
        args.extend(["--title", title])
    if live:
        args.append("--live")
    _emit(run("emu-quick-settings.py", args, timeout=15))


# --- decky ---


@decky_app.command("list")
def decky_list() -> None:
    """Known plugins and ensure scripts."""
    table = Table(title="decky")
    table.add_column("key", style="cyan")
    table.add_column("QAM name")
    table.add_column("ensure")
    for key, (name, script) in DECKY.items():
        table.add_row(key, name, script)
    console.print(table)
    console.print("[dim]reload uses the QAM name: fgpc decky reload 'Pad Hide'[/dim]")


@decky_app.command("reload")
def decky_reload(
    name: str = typer.Argument(..., help="QAM display name, e.g. Pad Hide"),
) -> None:
    """loader/reload_plugin (display name, not folder)."""
    root = playbook_root()
    cmd = [
        "bash",
        "-c",
        'source "$1/scripts/common.sh" && load_env "$1" && decky_reload_plugin "$2"',
        "fgpc-decky",
        str(root),
        name,
    ]
    proc = subprocess.run(cmd, env=os.environ.copy())
    raise typer.Exit(proc.returncode)


@decky_app.command("install")
def decky_install(
    key: str = typer.Argument(..., help="pads | hide | screen | quick | sunshine | playbook | tailscale"),
) -> None:
    """Run the matching ensure-*-decky.sh (copy + reload)."""
    hit = DECKY.get(key)
    if not hit:
        err(f"unknown {key}. try: {', '.join(DECKY)}")
        raise typer.Exit(2)
    result = run(hit[1], json_out=False, timeout=40, stream=True)
    raise typer.Exit(result.rc)


# --- saves ---


@saves_app.command("status")
def saves_status() -> None:
    """Syncthing ensure (idempotent; prints state)."""
    result = run("ensure-syncthing.sh", json_out=False, timeout=40, stream=True)
    raise typer.Exit(result.rc)


@saves_app.command("ensure")
def saves_ensure() -> None:
    """Restore official Syncthing v2 + Eden/Azahar folders."""
    saves_status()


def main() -> int:
    try:
        app()
    except typer.Exit as exc:
        return int(exc.exit_code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
