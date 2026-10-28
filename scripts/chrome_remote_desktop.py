#!/usr/bin/python3
"""Chrome Remote Desktop host texts and checks for SteamOS.

The official Google host lives under /opt/google/chrome-remote-desktop.
SteamOS updates wipe `/`, so the playbook keeps the payload on /home and
restores a symlink plus chrome-remote-desktop@USER.service.

Google account + PIN setup is never automated.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEB_URL = "https://dl.google.com/linux/direct/chrome-remote-desktop_current_amd64.deb"
HOST_BIN = "/opt/google/chrome-remote-desktop/chrome-remote-desktop"
START_HOST = "/opt/google/chrome-remote-desktop/start-host"
XORG_DEBIAN = "/usr/lib/xorg/Xorg"
XORG_ARCH = "/usr/lib/Xorg"
HEADLESS_URL = "https://remotedesktop.google.com/headless"
ACCESS_URL = "https://remotedesktop.google.com/access"
CHROME_FLATPAK = "com.google.Chrome"


def session_file_text() -> str:
    return """# Chrome Remote Desktop virtual session on this Steam Machine.
# Xvfb + Plasma X11 — not Game Mode HDMI and not the live Plasma seat.
# Plasma may not like two concurrent sessions; connect while Game Mode is up
# when possible. Do not replace gamescope / kwin_wayland.
exec /usr/bin/startplasma-x11
"""


def pam_file_text() -> str:
    # Debian package includes common-auth; SteamOS/Arch uses system-remote-login.
    return """#%PAM-1.0
auth       include    system-remote-login
account    include    system-remote-login
password   include    system-remote-login
session    include    system-remote-login
"""


def system_unit_text() -> str:
    return """[Unit]
Description=Chrome Remote Desktop instance for %i
After=network.target systemd-user-sessions.service
Conflicts=chrome-remote-desktop.service

[Service]
Type=simple
User=%i
Environment=XDG_SESSION_CLASS=user XDG_SESSION_TYPE=x11
Environment=CHROME_REMOTE_DESKTOP_USE_XVFB=1
Environment=CHROME_REMOTE_DESKTOP_DEFAULT_DESKTOP_SIZES=1920x1080,2560x1440,3840x2160
PAMName=chrome-remote-desktop
TTYPath=/dev/chrome-remote-desktop
ExecStart=/opt/google/chrome-remote-desktop/chrome-remote-desktop --start --new-session
ExecReload=/opt/google/chrome-remote-desktop/chrome-remote-desktop --reload
ExecStop=/opt/google/chrome-remote-desktop/chrome-remote-desktop --stop
StandardOutput=journal
StandardError=inherit
RestartForceExitStatus=41

[Install]
WantedBy=multi-user.target
"""


def host_json_paths(config_dir: str | Path) -> list[Path]:
    root = Path(config_dir)
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("host#*.json") if p.is_file() and p.stat().st_size > 0)


def host_registered(config_dir: str | Path) -> bool:
    for path in host_json_paths(config_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if data.get("host_id") or data.get("private_key") or data.get("xmpp_login"):
            return True
    return False


def service_name(user: str) -> str:
    return f"chrome-remote-desktop@{user}.service"


def usage_text(user: str = "deck") -> str:
    svc = service_name(user)
    return f"""Chrome Remote Desktop is a virtual Plasma X11 desktop (Xvfb).
It is not Game Mode HDMI, not Sunshine/Moonlight, and not the live Plasma seat.
Do not replace Decky Sunshine, sunshine-ds, or kwin_wayland.

Install / restore (after a SteamOS update):
  export XDG_RUNTIME_DIR=/run/user/$(id -u)
  ./scripts/ensure-chrome-remote-desktop.sh

First-time host registration (Google account + PIN — never put those in the repo):
  1. On a browser signed into the Google account you will use:
       {HEADLESS_URL}
  2. Begin → Next → Authorize.
  3. Copy the Debian/Linux command (starts with DISPLAY= .../start-host --code=...).
  4. On this Steam Machine, paste and run that command as {user}.
     Set a 6-digit PIN when asked. Wait for "Host ready to receive connections."
  5. Then:
       sudo systemctl enable --now {svc}
       ./scripts/crd.sh status

Connect from another computer or phone:
  1. Open {ACCESS_URL} (or the Chrome Remote Desktop Android app).
  2. Sign in with the same Google account.
  3. Click this machine and enter the PIN.

Useful commands:
  ./scripts/crd.sh status
  ./scripts/crd.sh start
  ./scripts/crd.sh stop
  ./scripts/crd.sh restart
  sudo journalctl -u {svc} -n 80 --no-pager

Do not pgrep -f / pkill -f sunshine. Do not sudo systemctl --user.
"""


def setup_manual_text(user: str = "deck") -> str:
    svc = service_name(user)
    return f"""# On any browser (phone/laptop), signed into the Google account:
#   {HEADLESS_URL}
# Begin → Next → Authorize, then paste the Debian/Linux command here as {user}.
# Example shape (the --code= value is short-lived; copy a fresh one):
DISPLAY= {START_HOST} --code="4/..." --redirect-url="https://remotedesktop.google.com/_/oauthredirect" --name="$(hostname)"
# Set a 6-digit PIN. Then:
sudo systemctl enable --now {svc}
export XDG_RUNTIME_DIR=/run/user/$(id -u)
./scripts/crd.sh status
# Connect from {ACCESS_URL} (same Google account + PIN).
# Virtual Plasma session — not Game Mode HDMI / Sunshine.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("session", "pam", "unit", "registered", "usage", "setup-manual", "service", "self-test"),
    )
    parser.add_argument("--user", default="deck")
    parser.add_argument("--config-dir", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.action == "session":
        print(session_file_text(), end="")
        return 0
    if args.action == "pam":
        print(pam_file_text(), end="")
        return 0
    if args.action == "unit":
        print(system_unit_text(), end="")
        return 0
    if args.action == "registered":
        config = args.config_dir or str(Path.home() / ".config" / "chrome-remote-desktop")
        return 0 if host_registered(config) else 1
    if args.action == "usage":
        print(usage_text(args.user), end="")
        return 0
    if args.action == "setup-manual":
        print(setup_manual_text(args.user), end="")
        return 0
    if args.action == "service":
        print(service_name(args.user))
        return 0
    if args.action == "self-test":
        return self_test()
    return 1


def self_test() -> int:
    session = session_file_text()
    assert "startplasma-x11" in session
    assert "Game Mode" in session
    pam = pam_file_text()
    assert "system-remote-login" in pam
    assert "common-auth" not in pam
    unit = system_unit_text()
    assert "chrome-remote-desktop --start --new-session" in unit
    assert "CHROME_REMOTE_DESKTOP_USE_XVFB=1" in unit
    assert "WantedBy=multi-user.target" in unit
    assert service_name("deck") == "chrome-remote-desktop@deck.service"
    usage = usage_text("deck")
    assert HEADLESS_URL in usage
    assert ACCESS_URL in usage
    assert "ensure-chrome-remote-desktop.sh" in usage
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
