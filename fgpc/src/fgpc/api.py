"""JSON dump/run for Decky FGPC and later web. No Typer/Rich required.

Catalog (groups, examples, tips, help) is the source of truth. Actions call
playbook scripts via ``fgpc.invoke`` — do not reimplement hide/bind/stream.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fgpc import __version__
from fgpc.catalog import EXAMPLES, GROUPS, QAM_GROUPS, TIPS, TOPIC_HELP, WEB_GROUPS
from fgpc.invoke import Result, run
from fgpc.playbook import playbook_root

# QAM / API must never start bootstrap, post-update, or Plasma mode switch.
REFUSED = {
    "host",
    "mode",
    "complete",
    "bootstrap",
    "post-update",
    "decky",
}


def _last_line(text: str, rc: int) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else f"rc={rc}"


def _as_dict(result: Result) -> dict[str, Any]:
    if isinstance(result.data, dict):
        data = dict(result.data)
        data.setdefault("ok", result.rc == 0)
        data["rc"] = result.rc
        if result.stderr and not data.get("message"):
            data["message"] = result.stderr.strip()[:400]
        return data
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    return {
        "ok": result.rc == 0,
        "rc": result.rc,
        "message": _last_line(text, result.rc)[:400],
    }


def _script_text(name: str, args: list[str], timeout: float = 10) -> dict[str, Any]:
    result = run(name, args, json_out=False, timeout=timeout)
    text = (result.stdout or result.stderr or "").strip()
    return {
        "ok": result.rc == 0,
        "rc": result.rc,
        "message": _last_line(text, result.rc),
        "text": text[:1200],
    }


def _script_json(name: str, args: list[str], timeout: float = 12) -> dict[str, Any]:
    return _as_dict(run(name, args, json_out=True, timeout=timeout))


def _live_status() -> dict[str, Any]:
    out: dict[str, Any] = {}

    def stream() -> dict[str, Any]:
        desk = _script_text("ensure-sunshine-ds.sh", ["--status"], timeout=8)
        kms = _script_text("ensure-sunshine-ds-gamemode.sh", ["--status"], timeout=8)
        return {
            "ok": bool(desk.get("ok") or kms.get("ok")),
            "desktop": desk,
            "gamemode": kms,
            "port": 48200,
            "note": "Game Mode Moonlight is :48200, not Decky :47989.",
        }

    def screen() -> dict[str, Any]:
        return _script_json("second-screen-windows.py", ["status"], timeout=10)

    def pad() -> dict[str, Any]:
        return _script_json("bind-gamepad.py", ["status"], timeout=12)

    def hide() -> dict[str, Any]:
        return _script_json("hide-controllers.py", ["list"], timeout=10)

    def emu() -> dict[str, Any]:
        return _script_json("emu-quick-settings.py", ["status"], timeout=10)

    with ThreadPoolExecutor(max_workers=5) as pool:
        f_stream = pool.submit(stream)
        f_screen = pool.submit(screen)
        f_pad = pool.submit(pad)
        f_hide = pool.submit(hide)
        f_emu = pool.submit(emu)
        out["stream"] = f_stream.result()
        out["screen"] = f_screen.result()
        out["pad"] = f_pad.result()
        out["hide"] = f_hide.result()
        out["emu"] = f_emu.result()
    return out


def dump(*, live: bool = True) -> dict[str, Any]:
    """Catalog plus optional live stream/screen/pad/hide/emu status."""
    payload: dict[str, Any] = {
        "ok": True,
        "version": __version__,
        "playbook": str(playbook_root()),
        "groups": [{"name": name, "blurb": blurb} for name, blurb in GROUPS],
        "examples": [{"cmd": cmd, "why": why} for cmd, why in EXAMPLES],
        "tips": list(TIPS),
        "help": dict(TOPIC_HELP),
        "qam": list(QAM_GROUPS),
        "web": list(WEB_GROUPS),
    }
    if live:
        try:
            payload.update(_live_status())
        except Exception as exc:  # noqa: BLE001 — QAM still gets catalog
            payload["live_error"] = str(exc)[:300]
    return payload


def run_action(
    group: str,
    action: str,
    *,
    pad_id: str = "",
    mode: str = "",
    emu: str = "all",
    display: str = "",
    window_id: str = "",
    target: str = "",
    hidden: object = None,
    force: object = None,
    **_ignored: object,
) -> dict[str, Any]:
    """Run one catalog action. Never ``--force`` hide. Refuse host/mode/complete."""
    group = (group or "").strip().lower()
    action = (action or "").strip().lower()
    pad_id = (pad_id or "").strip()
    mode = (mode or "").strip().lower()
    emu = (emu or "all").strip().lower() or "all"
    display = (display or "").strip()
    window_id = (window_id or "").strip()
    target = (target or "").strip().lower()

    if group in REFUSED or action in REFUSED:
        return {
            "ok": False,
            "message": (
                f"{group} {action} is SSH-only (fgpc). "
                "QAM skips bootstrap, post-update, and mode switch."
            ),
        }
    if force not in (None, False, "", "0", "false", "no"):
        return {
            "ok": False,
            "message": "Decky / fgpc-api never passes --force (UI pad cannot hide itself).",
        }

    if group == "stream":
        return _run_stream(action, target)
    if group == "screen":
        return _run_screen(action, mode=mode, window_id=window_id, display=display)
    if group == "pad":
        return _run_pad(action, mode=mode, emu=emu)
    if group == "hide":
        return _run_hide(action, pad_id=pad_id, hidden=hidden)
    if group == "saves":
        if action in ("status", "ensure", ""):
            return _as_dict(
                run("ensure-syncthing.sh", json_out=False, timeout=40)
            )
        return {"ok": False, "message": "saves action: status | ensure"}
    if group == "emu" and action in ("status", ""):
        args = ["status"]
        if emu and emu != "all":
            args.extend(["--emu", emu])
        return _script_json("emu-quick-settings.py", args, timeout=12)
    return {"ok": False, "message": f"unknown {group} {action}. qam: {', '.join(QAM_GROUPS)}"}


def _run_stream(action: str, target: str) -> dict[str, Any]:
    if action in ("status", ""):
        return dump(live=True).get("stream") or {"ok": False, "message": "no stream status"}
    if action == "start-kms":
        return _as_dict(
            run(
                "ensure-sunshine-ds-gamemode.sh",
                ["--start-kms"],
                json_out=False,
                timeout=90,
            )
        )
    if action == "paint":
        return _as_dict(
            run(
                "sunshine-ds-gamemode-virtual.sh",
                ["--paint"],
                json_out=False,
                timeout=40,
            )
        )
    if action == "stop":
        return _as_dict(
            run(
                "ensure-sunshine-ds-gamemode.sh",
                ["--stop"],
                json_out=False,
                timeout=40,
            )
        )
    if action in ("close", "close-cemu", "close-azahar"):
        who = target or ("azahar" if action == "close-azahar" else "cemu")
        if who not in ("cemu", "azahar"):
            return {"ok": False, "message": "close target: cemu | azahar"}
        return _as_dict(run("sunshine-app-stop.sh", [who], json_out=False, timeout=20))
    if action in ("start", "desktop", "restart"):
        return {
            "ok": False,
            "message": "QAM stream is Game Mode :48200. Use start-kms (not --start, not desktop :48100).",
        }
    return {"ok": False, "message": "stream action: status | start-kms | paint | stop | close-cemu | close-azahar"}


def _run_screen(
    action: str,
    *,
    mode: str,
    window_id: str,
    display: str,
) -> dict[str, Any]:
    if action in ("status", "list", ""):
        cmd = "list" if action == "list" else "status"
        return _script_json("second-screen-windows.py", [cmd], timeout=12)
    if action in ("dual", "set-dual-screen"):
        if mode not in ("auto", "on", "off"):
            return {"ok": False, "message": "dual mode: auto | on | off"}
        return _script_json(
            "second-screen-windows.py",
            ["set-dual-screen", "--mode", mode],
            timeout=12,
        )
    if action in ("clock", "idle", "paint"):
        return _script_json("second-screen-windows.py", ["idle"], timeout=25)
    if action == "show":
        if not window_id:
            return {"ok": False, "message": "Missing window id"}
        args = ["show", "--id", window_id]
        if display:
            args.extend(["--display", display])
        return _script_json("second-screen-windows.py", args, timeout=25)
    return {"ok": False, "message": "screen action: status | dual | clock | show | list"}


def _run_pad(action: str, *, mode: str, emu: str) -> dict[str, Any]:
    if action in ("status", "list", ""):
        cmd = "list" if action == "list" else "status"
        return _script_json("bind-gamepad.py", [cmd], timeout=12)
    if action == "mode":
        if mode not in ("shared", "multi"):
            return {"ok": False, "message": "pad mode: shared | multi"}
        return _script_json("bind-gamepad.py", ["set-mode", "--mode", mode], timeout=12)
    if action == "apply":
        if emu not in ("all", "cemu", "azahar", "eden"):
            return {"ok": False, "message": "emu: all | cemu | azahar | eden"}
        args = ["apply", "--emu", emu, "--force", "--all-sources"]
        if mode in ("shared", "multi"):
            args.extend(["--mode", mode])
        return _script_json("bind-gamepad.py", args, timeout=25)
    return {"ok": False, "message": "pad action: status | mode | apply"}


def _run_hide(action: str, *, pad_id: str, hidden: object) -> dict[str, Any]:
    if action in ("status", "list", ""):
        return _script_json("hide-controllers.py", ["list"], timeout=12)
    if action == "apply":
        return _script_json("hide-controllers.py", ["apply"], timeout=15)
    flag = ""
    if action in ("off", "hide"):
        flag = "hide"
    elif action in ("on", "show"):
        flag = "show"
    elif action == "set":
        if hidden is False or str(hidden).strip().lower() in (
            "0",
            "false",
            "no",
            "show",
            "on",
            "visible",
        ):
            flag = "show"
        else:
            flag = "hide"
    else:
        return {"ok": False, "message": "hide action: list | off | on | apply"}
    if not pad_id:
        return {"ok": False, "message": "Missing pad id"}
    # Never --force. hide-controllers.py refuses the UI pad.
    return _script_json(
        "hide-controllers.py",
        ["set", "--id", pad_id, "--hidden", flag],
        timeout=12,
    )


def self_test() -> dict[str, Any]:
    """Offline checks (no kernel hide, no kms start)."""
    data = dump(live=False)
    names = {row["name"] for row in data["groups"]}
    missing = {"stream", "screen", "pad", "hide", "emu", "decky"} - names
    if missing:
        return {"ok": False, "message": f"catalog missing {sorted(missing)}"}
    if not data["tips"] or "stream" not in data["help"]:
        return {"ok": False, "message": "catalog tips/help incomplete"}
    if list(data["qam"]) != list(QAM_GROUPS):
        return {"ok": False, "message": "qam groups drifted from catalog"}
    if list(data.get("web") or []) != list(WEB_GROUPS):
        return {"ok": False, "message": "web groups drifted from catalog"}
    refused = run_action("host", "bootstrap")
    if refused.get("ok") is not False:
        return {"ok": False, "message": "host bootstrap must be refused"}
    refused_mode = run_action("mode", "game")
    if refused_mode.get("ok") is not False:
        return {"ok": False, "message": "mode game must be refused"}
    refused_force = run_action("hide", "off", pad_id="usb:0000:0000:nope", force=True)
    if refused_force.get("ok") is not False or "force" not in (
        refused_force.get("message") or ""
    ).lower():
        return {"ok": False, "message": "--force must be refused"}
    refused_start = run_action("stream", "start")
    if refused_start.get("ok") is not False:
        return {"ok": False, "message": "stream start must be refused (use start-kms)"}
    return {"ok": True, "playbook": data["playbook"], "qam": data["qam"]}
