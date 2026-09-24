"""Arrow / number picker that works over SSH (stdlib termios, no extra TUI)."""

from __future__ import annotations

import sys
import termios
import tty

from rich.console import Console
from rich.table import Table

console = Console()


def _read_key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            rest = sys.stdin.read(2)
            return ch + rest
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def pick(title: str, options: list[tuple[str, str]]) -> str | None:
    """Return the chosen value. Empty options or non-TTY → None."""
    if not options:
        return None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        table = Table(title=title)
        table.add_column("#")
        table.add_column("command")
        table.add_column("why")
        for i, (label, _value) in enumerate(options, 1):
            table.add_row(str(i), label, "")
        console.print(table)
        console.print("[dim]not a TTY — run a command from the table[/dim]")
        return None
    idx = 0
    while True:
        console.clear()
        console.print(f"[bold cyan]{title}[/bold cyan]")
        console.print("[dim]↑↓ arrows  enter  q quit  numbers work too[/dim]\n")
        for i, (label, _value) in enumerate(options):
            mark = "[reverse]" if i == idx else ""
            end = "[/reverse]" if i == idx else ""
            console.print(f"  {mark}{i + 1:2d}. {label}{end}")
        key = _read_key()
        if key in ("q", "Q", "\x03"):
            return None
        if key in ("\r", "\n"):
            return options[idx][1]
        if key == "\x1b[A":
            idx = (idx - 1) % len(options)
        elif key == "\x1b[B":
            idx = (idx + 1) % len(options)
        elif key.isdigit():
            n = int(key)
            if 1 <= n <= min(9, len(options)):
                return options[n - 1][1]
