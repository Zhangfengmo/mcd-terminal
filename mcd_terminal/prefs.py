"""Remember the user's last store / address so the next order needs fewer flags.

Stored as JSON in $MCD_HOME/prefs.json (default ~/.config/mcd-terminal). Nothing
secret is kept here: no token, only store codes and an address id.
Demo mode keeps prefs in memory so it never touches the real file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def home() -> Path:
    return Path(os.environ.get("MCD_HOME") or os.path.join(os.path.expanduser("~"), ".config", "mcd-terminal"))


def _path() -> Path:
    return home() / "prefs.json"


def prefs_path() -> Path:
    return _path()


# ------------------------------------------------------------------ token
def token_path() -> Path:
    return home() / "token"


def load_token() -> str | None:
    try:
        t = token_path().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return t or None


def save_token(token: str) -> Path:
    """Write the token readable by the current user only (0600 on Unix)."""
    p = token_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token.strip() + "\n")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return p


def clear_token() -> bool:
    try:
        token_path().unlink()
        return True
    except OSError:
        return False


class Prefs:
    def __init__(self, persist: bool = True) -> None:
        self.persist = persist
        self.data: dict[str, Any] = {}
        if persist:
            try:
                self.data = json.loads(_path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.data = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def unset(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
            self._save()

    def set(self, key: str, value: Any) -> None:
        if value is None:
            self.unset(key)
            return
        self.data[key] = value
        self._save()

    def _save(self) -> None:
        if not self.persist:
            return
        try:
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass  # remembering is a convenience, never a failure
