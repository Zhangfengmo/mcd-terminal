"""Non-blocking keyboard for real-time terminal games (macOS / Linux / Windows)."""
from __future__ import annotations

import os
import sys
import time


class Keys:
    """`with Keys() as k: k.poll(0.05)` -> 'left' / 'right' / 'up' / 'down' / 'space' / 'enter' / 'q' / 'esc' / char / None."""

    def __enter__(self) -> "Keys":
        if os.name != "nt":
            import termios
            import tty
            self._fd = sys.stdin.fileno()
            self._old = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc: object) -> None:
        if os.name != "nt":
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)

    def poll(self, timeout: float) -> str | None:
        if os.name == "nt":  # pragma: no cover - Windows
            import msvcrt
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\x00", "\xe0"):
                        return {"K": "left", "M": "right", "H": "up", "P": "down"}.get(msvcrt.getwch())
                    return _name(ch)
                time.sleep(0.01)
            return None
        import select
        if not select.select([self._fd], [], [], timeout)[0]:
            return None
        data = os.read(self._fd, 16)
        while data in (b"\x1b", b"\x1b[", b"\x1bO") and select.select([self._fd], [], [], 0.05)[0]:
            data += os.read(self._fd, 16)
        text = data.decode("utf-8", "ignore")
        if text.startswith("\x1b"):
            return {"[D": "left", "OD": "left", "[C": "right", "OC": "right",
                    "[A": "up", "OA": "up", "[B": "down", "OB": "down"}.get(text[1:3], "esc" if text == "\x1b" else None)
        return _name(text[:1])


def _name(ch: str) -> str | None:
    if ch == "\x03":
        raise KeyboardInterrupt
    return {" ": "space", "\r": "enter", "\n": "enter", "\x1b": "esc", "a": "left", "d": "right",
            "A": "left", "D": "right", "Q": "q"}.get(ch, ch or None)


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()
