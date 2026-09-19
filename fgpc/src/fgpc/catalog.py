"""Command docs, examples, and tips. Keep this the human catalog."""

from __future__ import annotations

GROUPS = [
    ("host", "Bootstrap, post-update, health"),
    ("mode", "Plasma Desktop DS vs Game Mode"),
    ("stream", "Moonlight / sunshine-ds :48100 and :48200"),
    ("screen", "Second screen / GamePad clock / windows"),
    ("pad", "EmuPads mux and emulator binds"),
    ("hide", "Kernel-unplug extra pads (NMH3)"),
    ("emu", "Eden / Azahar / Cemu quick graphics"),
    ("decky", "Install / reload QAM plugins"),
    ("saves", "Syncthing Eden / Azahar mesh"),
]

EXAMPLES = [
    ("fgpc", "Home + arrow menu"),
    ("fgpc tips", "Do-not-rediscover rules"),
    ("fgpc pad list", "Host pads (Thor / Xbox / …)"),
    ("fgpc hide list", "Which pads can look unplugged"),
    ("fgpc hide off usb:045e:028e:5F19FC0A", "NMH3: hide the physical Xbox"),
    ("fgpc stream status", "Desktop :48100 + Game Mode :48200"),
    ("fgpc stream gamemode start-kms", "kms when :2 is already up"),
    ("fgpc screen list", "gamescope windows on :0/:1/:2"),
    ("fgpc screen clock", "Idle clock on Thor bottom"),
    ("fgpc mode game", "Leave Plasma, stop desktop DS"),
    ("fgpc emu status --emu eden", "Emu Quick rows"),
    ("fgpc decky reload 'Pad Hide'", "QAM after a plugin edit"),
    ("fgpc complete install", "Bash/Zsh autocomplete"),
]

TIPS = [
    "Moonlight dual-stream in Game Mode is :48200 (white tile), not Decky :47989.",
    "Never pgrep -f / pkill -f sunshine. Use pgrep -x sunshine-ds / sunshine-ds-kms.",
    "Never sudo systemctl --user (no user bus). export XDG_RUNTIME_DIR=/run/user/$(id -u).",
    "Do not --start kms while headless :2 is already up — use --start-kms.",
    "Do not authorized=0 a USB hub (1-1). The Xbox leaf on this box is 1-1.3.",
    "The pad driving Steam/QAM cannot hide itself. Decky never passes --force.",
    "Do not EVIOCGRAB the Sunshine pad — Steam needs it for overlay / QAM.",
    "Do not inherit Steam SDL_GAMECONTROLLER_IGNORE_DEVICES.",
    "EmuPads sinks 1209:e301/e302 are the bind target, not Sunshine pads.",
    "FOCUSED_APP=769 is Home/Library (mute), not Exit. Exit is SIGTERM only.",
    "TAILSCALE_HOSTNAME is steammachine. Never --reset / --ssh on this node.",
]

TOPIC_HELP = {
    "host": """Recover after a SteamOS update or check the box.

  fgpc host status       light: kms / mux / plugins
  fgpc host health       full ./health-check.sh
  fgpc host post-update  ./post-update.sh
  fgpc host bootstrap    ./bootstrap.sh
""",
    "mode": """Plasma dual-stream vs Game Mode.

  fgpc mode status
  fgpc mode desktop      sunshine-ds :48100 + Virtual-sunshine-ds
  fgpc mode game         --stop desktop DS, then steamosctl
""",
    "stream": """Two playbook servers (Decky :47989 stays).

  fgpc stream status
  fgpc stream desktop start|stop|restart
  fgpc stream gamemode start|start-kms|stop|paint
  fgpc stream close cemu|azahar
""",
    "screen": """Second Screen / GamePad clock.

  fgpc screen status
  fgpc screen dual auto|on|off
  fgpc screen list
  fgpc screen show --id 0x123 --display :1
  fgpc screen clock
""",
    "pad": """EmuPads mux. Emulators bind P1/P2.

  fgpc pad list|status
  fgpc pad mode shared|multi
  fgpc pad apply --emu all --mode shared
  fgpc pad bind cemu --cemu-p1 gamepad
""",
    "hide": """Kernel hide extra pads (NMH3). Cable stays.

  fgpc hide list
  fgpc hide off <id>     looks unplugged
  fgpc hide on <id>      restore
  fgpc hide apply        re-apply ~/.config/pad-hide/hidden.json
""",
    "emu": """Emu Quick graphics (do not touch binds / 4GB Engage).

  fgpc emu status --emu eden
  fgpc emu set --emu eden --key resolution_setup --value 2
""",
    "decky": """Copy + reload. Display name, not folder.

  fgpc decky list
  fgpc decky reload 'Pad Hide'
  fgpc decky install hide|pads|screen|quick|sunshine|tailscale
""",
    "saves": """Official Syncthing mesh (not GTK / decky-syncthing).

  fgpc saves status
  fgpc saves ensure
""",
}
