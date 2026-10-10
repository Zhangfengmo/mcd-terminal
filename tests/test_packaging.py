"""Every subpackage must be listed in pyproject, or installed builds (and the release binaries) miss it."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_all_subpackages_listed():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    listed = set(re.findall(r'"(mcd_terminal[\w.]*)"', re.search(r"^packages = \[(.*)\]", text, re.M).group(1)))
    found = {".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "mcd_terminal").rglob("*.py")
             if "__pycache__" not in p.parts}
    assert found <= listed, f"add to [tool.setuptools] packages: {sorted(found - listed)}"
