"""麦麦老虎机：主食、小食、饮料三轴一起转，停下来的组合按你的券和积分算好实付；不满意再转。"""
from __future__ import annotations

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .kitchen import REELS


def reel_cell(name: str, spinning: bool) -> Panel:
    return Panel(Align.center(Text(name, style="dim" if spinning else "bold"), vertical="middle"),
                 width=16, height=5, border_style="#ffc93c" if not spinning else "#8f8aa6")


def render(names: list[str], keys: list[str], spinning: list[bool], footer: Text | None = None) -> Panel:
    row = Table.grid(padding=(0, 1))
    for _ in names:
        row.add_column(justify="center")
    row.add_row(*[Text(REELS[k][0], style="dim") for k in keys])
    row.add_row(*[reel_cell(n, s) for n, s in zip(names, spinning)])
    body = [Align.center(row)]
    if footer is not None:
        body += [Text(""), Align.center(footer)]
    return Panel(Group(*body), title="[bold]麦麦老虎机[/]", border_style="#ff5a36", expand=False)
