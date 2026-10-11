"""翻翻乐：4×4 张牌，8 种餐品各两张。方向键移动，空格翻牌，配对全部翻开，步数越少越好。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

N = 4
# key: (emoji, ascii, name)
KINDS = {
    "burger": ("🍔", "B", "汉堡"), "fries": ("🍟", "F", "薯条"), "chicken": ("🍗", "N", "麦乐鸡"),
    "drink": ("🥤", "D", "可乐"), "coffee": ("☕", "C", "咖啡"), "icecream": ("🍦", "I", "冰淇淋"),
    "pie": ("🥧", "P", "派"), "breakfast": ("🍳", "E", "早餐"),
}
HIDE_AFTER = 0.8   # seconds a mismatched pair stays face up


@dataclass
class Memory:
    seed: int | None = None
    cards: list[str] = field(default_factory=list)
    done: set[int] = field(default_factory=set)
    open: list[int] = field(default_factory=list)
    cur: int = 0
    moves: int = 0
    t: float = 0.0
    started: bool = False
    hide_in: float = 0.0

    def __post_init__(self) -> None:
        if not self.cards:
            self.cards = [k for k in KINDS for _ in range(2)]
            random.Random(self.seed).shuffle(self.cards)

    @property
    def won(self) -> bool:
        return len(self.done) == len(self.cards)

    def move(self, key: str) -> None:
        r, c = divmod(self.cur, N)
        r = (r + {"up": -1, "down": 1}.get(key, 0)) % N
        c = (c + {"left": -1, "right": 1}.get(key, 0)) % N
        self.cur = r * N + c

    def flip(self, i: int | None = None) -> None:
        i = self.cur if i is None else i
        if self.won or i in self.done or i in self.open:
            return
        if len(self.open) == 2:          # flipping again hides a mismatched pair right away
            self.open = []
        self.started = True
        self.open.append(i)
        if len(self.open) < 2:
            return
        self.moves += 1
        a, b = self.open
        if self.cards[a] == self.cards[b]:
            self.done |= {a, b}
            self.open = []
        else:
            self.hide_in = HIDE_AFTER

    def step(self, dt: float) -> None:
        if self.started and not self.won:
            self.t += dt
        if self.hide_in > 0:
            self.hide_in -= dt
            if self.hide_in <= 0 and len(self.open) == 2:
                self.open = []


def render(g: Memory, best: int | None, ascii_only: bool = False) -> Panel:
    rows = []
    for r in range(N):
        line = Text("  ")
        for c in range(N):
            i = r * N + c
            emoji, a, _ = KINDS[g.cards[i]]
            face = (f" {a} " if ascii_only else f" {emoji}") if (i in g.done or i in g.open) else (" ? " if ascii_only else " ❓")
            style = "#19a974" if i in g.done else ("bold #ff5a36" if i in g.open else "#7a5cff")
            if i == g.cur and not g.won:
                style += " reverse"
            line.append(f"[{face}]", style=style)
            line.append(" ")
        rows += [line, Text("")]
    head = Text.assemble(("步数 ", "dim"), (f"{g.moves:<3}", "bold #ff5a36"), ("  用时 ", "dim"), (f"{int(g.t)} 秒", "bold"),
                         ("  最少 ", "dim"), (str(best) if best else "-", "bold"))
    foot = Text("全部配对！" if g.won else "方向键移动，空格翻牌，Q 退出", style="bold #19a974" if g.won else "dim")
    return Panel(Group(Align.center(head), Text(""), *rows, Align.center(foot)),
                 title="[bold]翻翻乐[/]", border_style="#ffc93c", width=N * 7 + 6)
