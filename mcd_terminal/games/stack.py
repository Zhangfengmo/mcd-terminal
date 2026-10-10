"""汉堡叠叠乐：一层馅料左右滑动，按空格放下；没对齐的部分会被切掉，越叠越窄。"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

W = 24          # board width in columns
SHOWN = 12      # how many layers of the tower are visible

# name, color — cycles bottom to top (the bottom bun is fixed)
LAYERS = [("牛肉饼", "#7a3f22"), ("芝士", "#ffc93c"), ("生菜", "#19a974"), ("番茄", "#ff5a36"),
          ("洋葱", "#f3e6ff"), ("鸡排", "#e0893a"), ("酸黄瓜", "#5c9e3b"), ("培根", "#c0392b")]
BUN = "#f2a65a"


@dataclass
class Layer:
    x: int
    w: int
    color: str
    name: str


@dataclass
class Stack:
    seed: int | None = None
    tower: list[Layer] = field(default_factory=list)
    moving: Layer | None = None
    dir: int = 1
    pos: float = 0.0
    perfect: int = 0
    flash: str = ""
    flash_t: float = 0.0
    over: bool = False

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)
        self.tower = [Layer(4, 16, BUN, "底层面包")]
        self._next()

    @property
    def layers(self) -> int:
        return len(self.tower) - 1

    @property
    def speed(self) -> float:      # columns per second
        return 9 + self.layers * 0.9

    def _next(self) -> None:
        top = self.tower[-1]
        name, color = LAYERS[(len(self.tower) - 1) % len(LAYERS)]
        self.dir = self.rng.choice([1, -1])
        self.pos = 0.0 if self.dir == 1 else float(W - top.w)
        self.moving = Layer(int(self.pos), top.w, color, name)

    def step(self, dt: float) -> None:
        if self.over or not self.moving:
            return
        self.flash_t = max(0.0, self.flash_t - dt)
        self.pos += self.dir * self.speed * dt
        hi = W - self.moving.w
        if self.pos <= 0 or self.pos >= hi:
            self.pos = max(0.0, min(float(hi), self.pos))
            self.dir *= -1
        self.moving.x = int(round(self.pos))

    def drop(self) -> None:
        if self.over or not self.moving:
            return
        top, m = self.tower[-1], self.moving
        left, right = max(top.x, m.x), min(top.x + top.w, m.x + m.w)
        width = right - left
        if width <= 0:
            self.over = True
            self.moving = None
            self.flash, self.flash_t = "掉下去了！", 3.0
            return
        if m.x == top.x:
            self.perfect += 1
            width = min(top.w + (1 if self.perfect % 3 == 0 else 0), W - left)   # every 3 perfect drops: a little wider
            self.flash, self.flash_t = ("完美！" if self.perfect % 3 else "完美 x3，变宽了！"), 1.0
        else:
            self.perfect = 0
        self.tower.append(Layer(left, width, m.color, m.name))
        self._next()


def render(g: Stack, best: int, ascii_only: bool = False) -> Panel:
    block = "#" if ascii_only else "█"
    lines: list[Text] = []
    if g.moving:
        t = Text(" " * g.moving.x)
        t.append(block * g.moving.w, style=g.moving.color)
        lines.append(t)
    else:
        lines.append(Text(""))
    lines.append(Text(""))
    shown = g.tower[-SHOWN:]
    pad = SHOWN - len(shown)
    lines += [Text("") for _ in range(pad)]
    for layer in reversed(shown):
        t = Text(" " * layer.x)
        t.append(block * layer.w, style=layer.color)
        lines.append(t)
    head = Text.assemble(("层数 ", "dim"), (f"{g.layers:<3}", "bold #ff5a36"), ("  最高 ", "dim"), (str(max(best, g.layers)), "bold"))
    foot = Text(g.flash if g.flash_t > 0 else "空格放下，Q 退出", style="bold #19a974" if g.flash_t > 0 else "dim")
    return Panel(Group(Align.center(head), Text(""), *lines, Text(""), Align.center(foot)),
                 title="[bold]汉堡叠叠乐[/]", border_style="#ffc93c", width=W + 4)
