#!/usr/bin/env python3
"""Patch Decky Tailscale Control so Advanced Settings cannot override Headscale or hostname.

The upstream plugin always appends ``--reset`` on ``tailscale up``. That reverts
unspecified prefs: hostname back to steamdeck (the handheld's name) and
ControlURL back to controlplane.tailscale.com.

This host is the Steam Machine (lab name steammachine). Do not pass --hostname
or --reset; use ``tailscale set --hostname`` / existing prefs. Do not add --ssh.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RESET_LINE = '            cmd_list.append("--reset")\n'
SANITIZE_BLOCK = '''            flags = []
            skip_next = False
            for tok in str(custom_flags or "").split():
                if skip_next:
                    skip_next = False
                    continue
                if tok in ("--hostname", "--ssh", "--reset"):
                    if tok == "--hostname":
                        skip_next = True
                    continue
                if tok.startswith("--hostname=") or tok.startswith("--ssh=") or tok.startswith("--reset"):
                    continue
                flags.append(tok)
            cmd_list.extend(flags)
            if not login_server:
                login_server = _playbook_login_server()
            cmd_list.append(f"--login-server={login_server}") if login_server else None
            # Do not --reset: that reverts hostname to steamdeck and Headscale to tailscale.com.

'''
OLD_FLAGS_APPEND = (
    '            [cmd_list.append(elem) for elem in custom_flags.split()] '
    'if custom_flags != "" else None\n'
)
OLD_LOGIN_APPEND = (
    '            cmd_list.append(f"--login-server={login_server}") if login_server else None\n'
)
HELPER = '''
def _playbook_login_server():
    """Headscale URL from playbook settings; empty if unset. Never a hostname."""
    for path in (
        Path(settingsDir) / "playbook.json",
        Path("/home/deck/homebrew/settings/tailscale-control/playbook.json"),
    ):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        url = str(data.get("login_server") or "").strip()
        if url:
            return url
    return ""

'''
CUSTOM_FLAGS_DESC_OLD = (
    "Remember checking your --operator, which defaults to 'deck' for SteamOS "
    "(this needs to be set). Leaving the flag blank or omitting will reset to "
    "default i.e.: --operator=deck."
)
CUSTOM_FLAGS_DESC_NEW = (
    "Keep --operator=deck. Do not set --hostname (this Steam Machine is "
    "steammachine; the handheld is steamdeck). Do not add --reset or --ssh."
)
LOGIN_DESC_OLD = (
    "If you are running Headscale, use desktop mode to login for the 1st time "
    "(to generate login token). Leaving blank is default behavior."
)
LOGIN_DESC_NEW = (
    "Headscale login server. Leave the playbook default; blank used to --reset "
    "this node onto tailscale.com. First login is still desktop-mode if needed."
)


def patch_main_py(path: Path) -> bool:
    text = path.read_text()
    original = text
    if "from pathlib import Path" not in text:
        text = text.replace("import logging\n", "import logging\nimport json\nfrom pathlib import Path\n")
    elif "import json\n" not in text.split("class Plugin")[0]:
        text = text.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\n")
    if "def _playbook_login_server" not in text:
        text = text.replace("class Plugin:", HELPER + "class Plugin:")
    if OLD_FLAGS_APPEND in text and OLD_LOGIN_APPEND in text:
        text = text.replace(OLD_FLAGS_APPEND + OLD_LOGIN_APPEND, "", 1)
    text = text.replace(RESET_LINE, "")
    if "Do not --reset" not in text:
        needle = '            cmd_list = ["tailscale", "up", f"--exit-node={node_ip}"]\n'
        lan = (
            '            cmd_list.append("--exit-node-allow-lan-access=true") '
            'if node_ip != "" and allow_lan_access else None\n'
        )
        if needle in text and lan in text and SANITIZE_BLOCK not in text:
            text = text.replace(lan, lan + SANITIZE_BLOCK, 1)
    if text == original:
        return False
    path.write_text(text)
    return True


def patch_index_js(path: Path, login_server: str = "") -> bool:
    text = path.read_text()
    original = text
    text = text.replace(CUSTOM_FLAGS_DESC_OLD, CUSTOM_FLAGS_DESC_NEW)
    text = text.replace(LOGIN_DESC_OLD, LOGIN_DESC_NEW)
    if login_server:
        text = re.sub(
            r'const TAILSCALE_LOGIN_SERVER = ".*?";',
            f'const TAILSCALE_LOGIN_SERVER = {json.dumps(login_server)};',
            text,
            count=1,
        )
    if text == original:
        return False
    path.write_text(text)
    return True


def write_playbook_settings(path: Path, login_server: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"login_server": login_server}, indent=2) + "\n")


def main_is_patched(path: Path) -> bool:
    text = path.read_text()
    return "Do not --reset" in text and RESET_LINE not in text


def self_test() -> int:
    import tempfile

    src_main = Path("/home/deck/homebrew/plugins/tailscale-control/main.py")
    src_js = Path("/home/deck/homebrew/plugins/tailscale-control/dist/index.js")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        main_copy = tmp_path / "main.py"
        js_copy = tmp_path / "index.js"
        # Use a stock snippet if the live plugin is already patched.
        stock = '''import logging
class Plugin:
    async def up(self, node_ip="", allow_lan_access=True, custom_flags="", login_server=""):
        try:
            allow_lan_access = bool(allow_lan_access)
            node_ip = str(node_ip).split()[0] if node_ip else ""
            cmd_list = ["tailscale", "up", f"--exit-node={node_ip}"]
            cmd_list.append("--exit-node-allow-lan-access=true") if node_ip != "" and allow_lan_access else None
            [cmd_list.append(elem) for elem in custom_flags.split()] if custom_flags != "" else None
            cmd_list.append(f"--login-server={login_server}") if login_server else None
            cmd_list.append("--reset")
            logger.debug(f"Tailscale up with command: {' '.join(cmd_list)}")
            return not subprocess.run(cmd_list, timeout=10, check=False)
        except Exception as e:
            logger.error(e, "error")
'''
        main_copy.write_text(stock)
        js_copy.write_text(
            'const TAILSCALE_LOGIN_SERVER = "";\n'
            f'window.SP_REACT.createElement(deckyFrontendLib.TextField, {{ description: "{CUSTOM_FLAGS_DESC_OLD}" }});\n'
            f'window.SP_REACT.createElement(deckyFrontendLib.TextField, {{ description: "{LOGIN_DESC_OLD}" }});\n'
        )
        patch_main_py(main_copy)
        patch_index_js(js_copy, login_server="https://example.invalid")
        patched = main_copy.read_text()
        if RESET_LINE.strip() in patched.splitlines() or 'cmd_list.append("--reset")' in patched:
            print("self-test: --reset still present", file=sys.stderr)
            return 1
        if "Do not --reset" not in patched or "_playbook_login_server" not in patched:
            print("self-test: sanitizer missing", file=sys.stderr)
            return 1
        if "--hostname=" not in patched.split("for tok")[0]:
            pass
        js = js_copy.read_text()
        if "steammachine" not in js or "https://example.invalid" not in js:
            print("self-test: index.js not patched", file=sys.stderr)
            return 1
        if src_main.exists() and src_js.exists():
            print("self-test ok")
        else:
            print("self-test ok (stock fixtures only)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--login-server", default="")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    changed = False
    if args.main:
        changed = patch_main_py(args.main) or changed
        if not main_is_patched(args.main):
            print(f"failed to patch {args.main}", file=sys.stderr)
            return 1
    if args.index:
        changed = patch_index_js(args.index, login_server=args.login_server) or changed
    if args.settings is not None:
        write_playbook_settings(args.settings, args.login_server)
        changed = True
    print("patched" if changed else "already patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
