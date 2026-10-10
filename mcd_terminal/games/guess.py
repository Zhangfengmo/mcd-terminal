"""麦德尔：每天一道题。给你一个购物车和你手上的券、积分，猜叠加之后最少要付多少钱。

和 Wordle 一样一天一题（同一天题目相同），最多猜 6 次；差 ¥0.5 以内算猜中。
"""
from __future__ import annotations

import hashlib
import random
from datetime import date

from .kitchen import Kitchen

TRIES = 6
CLOSE_FEN = 50


def daily_rng(day: date, salt: str = "") -> random.Random:
    seed = int(hashlib.sha256(f"maidle:{day.isoformat()}:{salt}".encode()).hexdigest()[:12], 16)
    return random.Random(seed)


def puzzle(k: Kitchen, day: date, salt: str = ""):
    """3–4 items, preferring carts where coupons or points actually change the answer."""
    rng = daily_rng(day, salt)
    best = None
    for _ in range(60):
        keys = rng.sample(["main", "side", "drink", "sweet"], rng.choice([3, 4]))
        got = k.roll(rng, keys, tries=1)
        if not got:
            continue
        items, plan = got
        interesting = plan.saving_fen > 0 and plan.pay_fen > 0
        if interesting:
            return items, plan
        best = best or got
    return best


def hint(guess_fen: int, answer_fen: int) -> str:
    diff = guess_fen - answer_fen
    if abs(diff) <= CLOSE_FEN:
        return "hit"
    if abs(diff) <= 300:
        return "warm_high" if diff > 0 else "warm_low"
    return "high" if diff > 0 else "low"


HINT_TEXT = {"hit": "猜中了！", "warm_high": "高了一点", "warm_low": "低了一点", "high": "高了", "low": "低了"}
HINT_MARK = {"hit": "🟩", "warm_high": "🟨", "warm_low": "🟨", "high": "🟥", "low": "🟦"}
