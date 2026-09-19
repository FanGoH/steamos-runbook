"""Rich output that stays readable over SSH (no images, no truecolor req)."""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(soft_wrap=True)


def banner() -> None:
    title = Text()
    title.append("fgpc", style="bold cyan")
    title.append("  FanGoH Gaming PC\n", style="bold")
    title.append("Steam Machine playbook · SSH-friendly · script-first", style="dim")
    console.print(Panel(title, border_style="cyan", box=box.ROUNDED))


def kv_table(title: str, rows: list[tuple[str, str]]) -> None:
    table = Table(title=title, box=box.SIMPLE, expand=False, show_header=False)
    table.add_column("k", style="cyan", no_wrap=True)
    table.add_column("v")
    for key, val in rows:
        table.add_row(key, str(val))
    console.print(table)


def _cell(value: Any) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return ""
    return str(value)


def dict_table(title: str, rows: list[dict[str, Any]], columns: list[str]) -> None:
    headers = {
        "can_disable": "can off",
        "connected": "up",
        "hidden": "hidden",
    }
    table = Table(title=title, box=box.SIMPLE, expand=True)
    for col in columns:
        table.add_column(headers.get(col, col), overflow="fold")
    for row in rows:
        table.add_row(*[_cell(row.get(col)) for col in columns])
    console.print(table)


def show_result(data: object | None, stdout: str = "", stderr: str = "") -> None:
    if isinstance(data, dict) and isinstance(data.get("pads"), list):
        cols = [
            c
            for c in (
                "id",
                "name",
                "js",
                "kind",
                "hidden",
                "connected",
                "can_disable",
                "ui",
            )
            if any(c in p for p in data["pads"])
        ]
        if not cols:
            cols = ["name", "js"]
        dict_table("pads", data["pads"], cols)
        extra = {k: v for k, v in data.items() if k != "pads"}
        if extra:
            console.print(JSON.from_data(extra))
        return
    if isinstance(data, dict) and isinstance(data.get("windows"), list):
        dict_table(
            "windows",
            data["windows"],
            [c for c in ("id", "name", "display", "width", "height") if True],
        )
        extra = {k: v for k, v in data.items() if k != "windows"}
        if extra:
            console.print(JSON.from_data(extra))
        return
    if data is not None:
        console.print(JSON.from_data(data))
        return
    if stdout.strip():
        console.print(stdout.rstrip())
    if stderr.strip():
        console.print(Text(stderr.rstrip(), style="yellow"))


def ok(msg: str) -> None:
    console.print(f"[green]ok[/green]  {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]warn[/yellow]  {msg}")


def err(msg: str) -> None:
    console.print(f"[red]err[/red]  {msg}")
