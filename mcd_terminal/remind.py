"""Put McDonald's dates into the user's own reminder apps.

- macOS: a reminder in the Reminders app (list "麦麦提醒"), via osascript. Text is passed as
  arguments, never pasted into the script, so a coupon title can't inject AppleScript.
- Windows / Linux / anything else: a calendar file (.ics) with an alarm, opened with the default
  calendar app (Outlook, Windows Calendar, GNOME Calendar…) so the user confirms the import.

Nothing here talks to McDonald's; it only writes reminders the user asked for.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIST_NAME = "麦麦提醒"


@dataclass
class Reminder:
    title: str
    when: datetime          # local time
    note: str = ""


# ------------------------------------------------------------------ .ics
def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics(reminders: list[Reminder]) -> str:
    """A calendar file with one 15-minute event + alarm per reminder (floating local time)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//mcd-terminal//麦麦提醒//ZH", "CALSCALE:GREGORIAN"]
    for r in reminders:
        start = r.when.strftime("%Y%m%dT%H%M%S")
        end = (r.when + timedelta(minutes=15)).strftime("%Y%m%dT%H%M%S")
        lines += ["BEGIN:VEVENT", f"UID:{uuid.uuid4()}@mcd-terminal", f"DTSTAMP:{stamp}",
                  f"DTSTART:{start}", f"DTEND:{end}", f"SUMMARY:{_ics_text(r.title)}"]
        if r.note:
            lines.append(f"DESCRIPTION:{_ics_text(r.note)}")
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_text(r.title)}", "TRIGGER:-PT0M",
                  "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_ics(reminders: list[Reminder], folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"mcd-reminders-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.ics"
    path.write_text(ics(reminders), encoding="utf-8")
    return path


def open_file(path: Path) -> bool:
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=True, timeout=15)
        else:
            subprocess.run(["xdg-open", str(path)], check=True, timeout=15)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# ------------------------------------------------------------------ macOS Reminders
_APPLESCRIPT = r'''
on run argv
  set listName to item 1 of argv
  set theTitle to item 2 of argv
  set theNote to item 3 of argv
  set d to current date
  set day of d to 1
  set year of d to (item 4 of argv) as integer
  set month of d to (item 5 of argv) as integer
  set day of d to (item 6 of argv) as integer
  set hours of d to (item 7 of argv) as integer
  set minutes of d to (item 8 of argv) as integer
  set seconds of d to 0
  tell application "Reminders"
    if not (exists list listName) then make new list with properties {name:listName}
    tell list listName
      if (exists (first reminder whose name is theTitle and completed is false)) then return "exists"
      make new reminder with properties {name:theTitle, body:theNote, remind me date:d}
    end tell
  end tell
  return "created"
end run
'''


def add_to_macos_reminders(r: Reminder) -> str:
    """Returns "created", "exists", or raises RuntimeError with a readable reason."""
    args = [LIST_NAME, r.title, r.note, str(r.when.year), str(r.when.month), str(r.when.day),
            str(r.when.hour), str(r.when.minute)]
    try:
        p = subprocess.run(["osascript", "-e", _APPLESCRIPT, *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"没能调用提醒事项：{e}")
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        if "-1743" in err or "not allowed" in err.lower():
            raise RuntimeError("系统还没允许终端控制“提醒事项”。请在 系统设置 → 隐私与安全性 → 自动化 里打开后再试")
        raise RuntimeError(err or "提醒事项返回了错误")
    return p.stdout.strip() or "created"


def is_macos() -> bool:
    return platform.system() == "Darwin"
