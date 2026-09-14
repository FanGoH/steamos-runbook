#!/usr/bin/env python3
"""Patch Decky Tailscale Control Advanced Settings for this Steam Machine.

Stock plugin ``up`` always appended ``--reset``, which reverted hostname to
steamdeck (the handheld) and ControlURL to tailscale.com.

Keep Headscale login-server, pass ``--hostname`` from .env (steammachine),
and never ``--reset`` / ``--ssh``. Manual bring-up is the same flags via
``tailscale_up_command``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RESET_LINE = '            cmd_list.append("--reset")\n'
LAN_LINE = (
    '            cmd_list.append("--exit-node-allow-lan-access=true") '
    'if node_ip != "" and allow_lan_access else None\n'
)
LOG_LINE = '            logger.debug(f"Tailscale up with command: {\' \'.join(cmd_list)}")\n'
SANITIZE_BLOCK = '''            flags = []
            skip_next = False
            saw_hostname = False
            saw_accept = False
            playbook_hostname = _playbook_hostname()
            for tok in str(custom_flags or "").split():
                if skip_next:
                    skip_next = False
                    continue
                if tok in ("--ssh", "--reset") or tok.startswith("--ssh=") or tok.startswith("--reset"):
                    continue
                if tok == "--hostname":
                    skip_next = True
                    if playbook_hostname:
                        flags.append(f"--hostname={playbook_hostname}")
                        saw_hostname = True
                    continue
                if tok.startswith("--hostname="):
                    flags.append(f"--hostname={playbook_hostname}" if playbook_hostname else tok)
                    saw_hostname = True
                    continue
                if tok == "--accept-routes" or tok.startswith("--accept-routes="):
                    saw_accept = True
                flags.append(tok)
            if playbook_hostname and not saw_hostname:
                flags.append(f"--hostname={playbook_hostname}")
            if not saw_accept:
                flags.append("--accept-routes")
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
def _playbook_settings():
    """Headscale URL + Steam Machine hostname from playbook settings."""
    for path in (
        Path(settingsDir) / "playbook.json",
        Path("/home/deck/homebrew/settings/tailscale-control/playbook.json"),
    ):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data:
            return data
    return {}

def _playbook_login_server():
    return str(_playbook_settings().get("login_server") or "").strip()

def _playbook_hostname():
    return str(_playbook_settings().get("hostname") or "").strip()

'''
GET_INITIAL_OLD = '''      function getInitialState(key, defaultState = 0, paramString = 'value') {
          const settingsString = localStorage.getItem(key);
          if (!settingsString) {
              return defaultState;
          }
          const storedSettings = JSON.parse(settingsString);
          return storedSettings[paramString] || defaultState;
      }'''
GET_INITIAL_NEW = '''      function getInitialState(key, defaultState = 0, paramString = 'value') {
          const settingsString = localStorage.getItem(key);
          if (!settingsString) {
              return defaultState;
          }
          const storedSettings = JSON.parse(settingsString);
          var value = storedSettings[paramString] || defaultState;
          if (key === LOCAL_STORAGE_KEY_TAILSCALE_UP_CUSTOM_FLAGS && typeof value === 'string') {
              if (!/--hostname=/.test(value) || /--hostname=steamdeck\\b/.test(value) || /--reset\\b/.test(value) || /--ssh\\b/.test(value)) {
                  value = DEFAULT_TAILSCALE_UP_CUSTOM_FLAGS;
                  localStorage.setItem(key, JSON.stringify({ value: value }));
              }
          }
          if (key === LOCAL_STORAGE_KEY_TAILSCALE_LOGIN_SERVER && !value && TAILSCALE_LOGIN_SERVER) {
              value = TAILSCALE_LOGIN_SERVER;
              localStorage.setItem(key, JSON.stringify({ value: value }));
          }
          return value;
      }'''
CUSTOM_FLAGS_DESC_OLD = (
    "Remember checking your --operator, which defaults to 'deck' for SteamOS "
    "(this needs to be set). Leaving the flag blank or omitting will reset to "
    "default i.e.: --operator=deck."
)
CUSTOM_FLAGS_DESC_PREV = (
    "Keep --operator=deck. Do not set --hostname (this Steam Machine is "
    "steammachine; the handheld is steamdeck). Do not add --reset or --ssh."
)
CUSTOM_FLAGS_DESC_NEW = (
    "Full up flags for this Steam Machine: --operator=deck --hostname=steammachine "
    "--accept-routes. Do not use steamdeck, --reset, or --ssh."
)
LOGIN_DESC_OLD = (
    "If you are running Headscale, use desktop mode to login for the 1st time "
    "(to generate login token). Leaving blank is default behavior."
)
LOGIN_DESC_PREV = (
    "Headscale login server. Leave the playbook default; blank used to --reset "
    "this node onto tailscale.com. First login is still desktop-mode if needed."
)
LOGIN_DESC_NEW = (
    "Headscale login server (same as the manual ./deck-tailscale up command). "
    "First login is still desktop-mode if needed. Do not leave this blank."
)


def default_custom_flags(hostname: str) -> str:
    host = hostname.strip() or "steammachine"
    return f"--operator=deck --hostname={host} --accept-routes"


def _ensure_imports(text: str) -> str:
    if "from pathlib import Path" not in text:
        text = text.replace("import logging\n", "import logging\nimport json\nfrom pathlib import Path\n")
    elif "import json\n" not in text.split("class Plugin")[0]:
        text = text.replace("from pathlib import Path\n", "import json\nfrom pathlib import Path\n")
    return text


def _ensure_helper(text: str) -> str:
    if "def _playbook_hostname(" in text:
        return text
    if "def _playbook_login_server(" in text:
        start = text.find("def _playbook_login_server(")
        end = text.find("class Plugin:")
        if start > 0 and end > start:
            return text[:start] + HELPER.lstrip("\n") + text[end:]
    return text.replace("class Plugin:", HELPER + "class Plugin:")


def _replace_up_flags(text: str) -> str:
    text = text.replace(RESET_LINE, "")
    if OLD_FLAGS_APPEND in text and OLD_LOGIN_APPEND in text:
        text = text.replace(OLD_FLAGS_APPEND + OLD_LOGIN_APPEND, "", 1)
    start = text.find(LAN_LINE)
    end = text.find(LOG_LINE)
    if start < 0 or end < 0 or end <= start:
        return text
    return text[: start + len(LAN_LINE)] + SANITIZE_BLOCK + text[end:]


def patch_main_py(path: Path) -> bool:
    text = path.read_text()
    original = text
    text = _ensure_imports(text)
    text = _ensure_helper(text)
    text = _replace_up_flags(text)
    if text == original:
        return False
    path.write_text(text)
    return True


def patch_index_js(path: Path, login_server: str = "", hostname: str = "") -> bool:
    text = path.read_text()
    original = text
    flags = default_custom_flags(hostname)
    text = text.replace(CUSTOM_FLAGS_DESC_OLD, CUSTOM_FLAGS_DESC_NEW)
    text = text.replace(CUSTOM_FLAGS_DESC_PREV, CUSTOM_FLAGS_DESC_NEW)
    text = text.replace(LOGIN_DESC_OLD, LOGIN_DESC_NEW)
    text = text.replace(LOGIN_DESC_PREV, LOGIN_DESC_NEW)
    text = re.sub(
        r'const DEFAULT_TAILSCALE_UP_CUSTOM_FLAGS = ".*?";',
        f"const DEFAULT_TAILSCALE_UP_CUSTOM_FLAGS = {json.dumps(flags)};",
        text,
        count=1,
    )
    if login_server:
        text = re.sub(
            r'const TAILSCALE_LOGIN_SERVER = ".*?";',
            f"const TAILSCALE_LOGIN_SERVER = {json.dumps(login_server)};",
            text,
            count=1,
        )
    if GET_INITIAL_OLD in text:
        text = text.replace(GET_INITIAL_OLD, GET_INITIAL_NEW)
    if text == original:
        return False
    path.write_text(text)
    return True


def write_playbook_settings(path: Path, login_server: str, hostname: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "login_server": login_server,
                "hostname": hostname,
                "custom_flags": default_custom_flags(hostname),
            },
            indent=2,
        )
        + "\n"
    )


def main_is_patched(path: Path) -> bool:
    text = path.read_text()
    return (
        "Do not --reset" in text
        and RESET_LINE not in text
        and "def _playbook_hostname(" in text
        and "flags.append(f\"--hostname={playbook_hostname}\")" in text
    )


def self_test() -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        main_copy = tmp_path / "main.py"
        js_copy = tmp_path / "index.js"
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
            'const DEFAULT_TAILSCALE_UP_CUSTOM_FLAGS = "--operator=deck";\n'
            'const LOCAL_STORAGE_KEY_TAILSCALE_UP_CUSTOM_FLAGS = "tailscaleUpCustomFlags";\n'
            'const LOCAL_STORAGE_KEY_TAILSCALE_LOGIN_SERVER = "tailscaleLoginServer";\n'
            + GET_INITIAL_OLD
            + "\n"
            + f'window.SP_REACT.createElement(deckyFrontendLib.TextField, {{ description: "{CUSTOM_FLAGS_DESC_OLD}" }});\n'
            + f'window.SP_REACT.createElement(deckyFrontendLib.TextField, {{ description: "{LOGIN_DESC_OLD}" }});\n'
        )
        patch_main_py(main_copy)
        patch_index_js(js_copy, login_server="https://example.invalid", hostname="steammachine")
        patched = main_copy.read_text()
        if 'cmd_list.append("--reset")' in patched:
            print("self-test: --reset still present", file=sys.stderr)
            return 1
        if "def _playbook_hostname(" not in patched or "--hostname={playbook_hostname}" not in patched:
            print("self-test: hostname inject missing", file=sys.stderr)
            return 1
        js = js_copy.read_text()
        if "--hostname=steammachine" not in js or "https://example.invalid" not in js:
            print("self-test: index.js flags missing", file=sys.stderr)
            return 1
        if "localStorage.setItem(key" not in js:
            print("self-test: localStorage host migrate missing", file=sys.stderr)
            return 1
        print("self-test ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--login-server", default="")
    parser.add_argument("--hostname", default="steammachine")
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
        changed = (
            patch_index_js(args.index, login_server=args.login_server, hostname=args.hostname)
            or changed
        )
    if args.settings is not None:
        write_playbook_settings(args.settings, args.login_server, args.hostname)
        changed = True
    print("patched" if changed else "already patched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
