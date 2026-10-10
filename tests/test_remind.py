"""Reminders: calendar files everywhere, the Reminders app on macOS."""
import subprocess
from datetime import datetime

import pytest

from mcd_terminal import remind
from mcd_terminal.remind import Reminder


def test_ics_has_an_alarm_and_escapes_text():
    text = remind.ics([Reminder("🎟 薯条券, 今天到期; 快用", datetime(2026, 10, 12, 10, 0), "第一行\n第二行")])
    assert "DTSTART:20261012T100000" in text and "BEGIN:VALARM" in text and "TRIGGER:-PT0M" in text
    assert "SUMMARY:🎟 薯条券\\, 今天到期\; 快用" in text
    assert "DESCRIPTION:第一行\\n第二行" in text
    assert text.endswith("END:VCALENDAR\r\n")


def test_write_ics_never_overwrites(tmp_path):
    r = [Reminder("a", datetime(2026, 10, 12, 10, 0))]
    assert remind.write_ics(r, tmp_path) != remind.write_ics(r, tmp_path)


def test_macos_reminder_passes_text_as_arguments(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="created\n", stderr="")
    monkeypatch.setattr(remind.subprocess, "run", fake_run)
    title = '活动 "引号" end tell'
    assert remind.add_to_macos_reminders(Reminder(title, datetime(2026, 10, 12, 9, 5), "备注")) == "created"
    cmd = seen["cmd"]
    assert cmd[:2] == ["osascript", "-e"] and title not in cmd[2]          # never pasted into the script
    assert cmd[3:] == ["麦麦提醒", title, "备注", "2026", "10", "12", "9", "5"]


def test_macos_permission_error_is_explained(monkeypatch):
    monkeypatch.setattr(remind.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 1, stdout="", stderr="execution error: Not authorized to send Apple events to Reminders. (-1743)"))
    with pytest.raises(RuntimeError, match="自动化"):
        remind.add_to_macos_reminders(Reminder("x", datetime(2026, 10, 12, 9, 0)))


def test_remind_time_never_in_the_past():
    from mcd_terminal.cli import _remind_at
    now = datetime(2026, 10, 12, 15, 0)
    assert _remind_at(now.date(), "10:00", now) == datetime(2026, 10, 12, 15, 5)
    assert _remind_at(datetime(2026, 10, 13).date(), "10:00", now) == datetime(2026, 10, 13, 10, 0)
