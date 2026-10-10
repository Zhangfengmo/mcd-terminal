"""接薯条：托盘左右移动，接住掉下来的薯条、麦乐鸡、汉堡，躲开火苗。

等餐的时候玩（--wait）：后台每 20 秒看一次订单，餐好了游戏就停下，显示取餐码。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

W, H = 14, 15          # board size in cells; each cell is 2 columns wide
TRAY = 3               # tray width in cells

# kind: (emoji, points, weight, ascii)
ITEMS = {
    "fries": ("🍟", 1, 60, "f"),
    "nugget": ("🍗", 2, 16, "n"),
    "burger": ("🍔", 5, 7, "B"),
    "hot": ("🔥", 0, 17, "x"),
}


@dataclass
class Drop:
    x: int
    y: float
    kind: str


@dataclass
class Fries:
    seed: int | None = None
    x: int = W // 2 - 1
    score: int = 0
    lives: int = 3
    combo: int = 0
    caught: dict[str, int] = field(default_factory=dict)
    drops: list[Drop] = field(default_factory=list)
    t: float = 0.0
    spawn_in: float = 0.4
    flash: str = ""
    flash_t: float = 0.0
    over: bool = False

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    @property
    def speed(self) -> float:          # rows per second
        return 4.0 + min(self.score, 120) / 12

    def move(self, dx: int) -> None:
        self.x = max(0, min(W - TRAY, self.x + dx))

    def step(self, dt: float) -> None:
        if self.over:
            return
        self.t += dt
        self.flash_t = max(0.0, self.flash_t - dt)
        self.spawn_in -= dt
        if self.spawn_in <= 0:
            kinds = list(ITEMS)
            kind = self.rng.choices(kinds, weights=[ITEMS[k][2] for k in kinds])[0]
            self.drops.append(Drop(self.rng.randrange(W), 0.0, kind))
            self.spawn_in = max(0.28, 0.9 - self.score / 150) * self.rng.uniform(0.7, 1.3)
        keep = []
        for d in self.drops:
            d.y += self.speed * dt
            if d.y >= H - 1:                       # reached the tray row
                if self.x <= d.x < self.x + TRAY:
                    self._catch(d.kind)
                elif d.kind != "hot":
                    self.combo = 0                 # dropped food breaks the combo
                continue
            keep.append(d)
        self.drops = keep

    def _catch(self, kind: str) -> None:
        if kind == "hot":
            self.lives -= 1
            self.combo = 0
            self._say("烫！-1 条命")
            if self.lives <= 0:
                self.over = True
            return
        self.combo += 1
        bonus = 1 + self.combo // 10
        self.score += ITEMS[kind][1] * bonus
        self.caught[kind] = self.caught.get(kind, 0) + 1
        if self.combo and self.combo % 10 == 0:
            self._say(f"连接 {self.combo} 个！得分 x{bonus}")

    def _say(self, msg: str) -> None:
        self.flash, self.flash_t = msg, 1.2


def render(g: Fries, best: int, status: str = "", ascii_only: bool = False) -> Panel:
    rows = []
    grid = [["  "] * W for _ in range(H)]
    for d in g.drops:
        y = min(H - 2, int(d.y))
        emoji, _, _, a = ITEMS[d.kind]
        grid[y][d.x] = (a + " ") if ascii_only else emoji
    for y in range(H - 1):
        rows.append(Text("".join(grid[y])))
    tray = Text("  " * g.x)
    tray.append("▀▀" * TRAY, style="bold #ffc93c")
    rows.append(tray)
    head = Text.assemble(("得分 ", "dim"), (f"{g.score:<4}", "bold #ff5a36"), ("  ", ""),
                         ("♥" * g.lives + "♡" * (3 - g.lives), "#ff5a36"), ("  最高 ", "dim"), (str(max(best, g.score)), "bold"),
                         (f"  连接 {g.combo}" if g.combo >= 3 else "", "#19a974"))
    foot = Text(g.flash if g.flash_t > 0 else (status or "← → 或 A D 移动，Q 退出"), style="dim" if not g.flash_t else "bold #19a974")
    return Panel(Group(Align.center(head), Text(""), *rows, Text(""), Align.center(foot)),
                 title="[bold]接薯条[/]", border_style="#ffc93c", width=W * 2 + 4)
