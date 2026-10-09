"""The packaged-binary loop test (packaging/e2e.py) must cover every command."""
import importlib.util
from pathlib import Path

import typer

from mcd_terminal.cli import app

spec = importlib.util.spec_from_file_location("e2e", Path(__file__).parent.parent / "packaging" / "e2e.py")
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)


def registered(t: typer.Typer, prefix: str = "") -> set[str]:
    names = {f"{prefix}{c.name or c.callback.__name__.replace('_', '-')}" for c in t.registered_commands
             if not c.hidden}
    for g in t.registered_groups:
        if g.hidden:
            continue
        names.add(f"{prefix}{g.name}")
        names |= registered(g.typer_instance, f"{prefix}{g.name} ")
    return names


def test_e2e_covers_every_command():
    assert registered(app) == set(e2e.COMMANDS)


def test_every_command_has_a_scenario_beyond_help():
    runs = [args for name, args, _, _ in e2e.scenarios("/tmp/x") if not name.startswith("help")]
    for c in e2e.COMMANDS:
        words = c.split()
        if words in (["skill"],):
            continue
        assert any(_has(args, words) for args in runs), c


def _has(args, words):
    a = [x for x in args if x not in ("--demo", "--json")]
    return a[:len(words)] == words or (words == ["today"] and a == [])


def test_every_alias_is_exercised():
    from mcd_terminal.cli import ALIASES
    runs = [[a for a in args if a not in ("--demo", "--json", "-j")] for _, args, _, _ in e2e.scenarios("/tmp/x")]
    for alias in [*ALIASES, "c"]:
        assert any(r[:1] == [alias] for r in runs), alias
