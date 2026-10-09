"""Build the standalone `mcd` program and package it for a GitHub release.

    python packaging/build.py            # -> release/mcd-<os>-<arch>.tar.gz (.zip on Windows)

Run on each target platform (CI does this for macOS / Linux / Windows, x64 and arm64).
The archive contains a single folder `mcd/` with the `mcd` executable inside; the
install scripts unpack it and put `mcd` on PATH.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build" / "pyinstaller"
OUT = ROOT / "release"
# Not used by mcd. Keep rich's markdown/pygments deps: typer's --help imports rich.markdown.
EXCLUDES = ["tkinter", "unittest", "pydoc_data", "sqlite3",
            "lib2to3", "ensurepip", "idlelib", "test", "xmlrpc"]


def target() -> tuple[str, str]:
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform)
    if os_name is None:
        sys.exit(f"unsupported platform {sys.platform}")
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    if arch is None:
        sys.exit(f"unsupported architecture {machine}")
    return os_name, arch


def main() -> None:
    import PyInstaller.__main__

    os_name, arch = target()
    shutil.rmtree(BUILD, ignore_errors=True)
    dist = BUILD / "dist"
    PyInstaller.__main__.run([
        str(ROOT / "packaging" / "mcd_entry.py"),
        "--name", "mcd", "--onedir", "--noconfirm", "--clean",
        "--distpath", str(dist), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--add-data", f"{ROOT / 'mcd_terminal' / 'skill' / 'SKILL.md'}{os.pathsep}mcd_terminal/skill",
        "--collect-submodules", "mcd_terminal",
        # rich loads its unicode width tables dynamically
        "--collect-submodules", "rich._unicode_data",
        *[arg for mod in EXCLUDES for arg in ("--exclude-module", mod)],
        # Debug symbols make up most of libpython on Linux; strip them (not supported on Windows).
        *([] if os_name == "windows" else ["--strip"]),
    ])

    exe = dist / "mcd" / ("mcd.exe" if os_name == "windows" else "mcd")
    # Full loop test of every command against the packaged binary (help, UI, --json, confirmations).
    r = subprocess.run([sys.executable, str(ROOT / "packaging" / "e2e.py"), str(exe)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    print(r.stdout)
    if r.returncode != 0:
        detail = (r.stdout or r.stderr or "").strip()[-1500:]
        if os.environ.get("GITHUB_ACTIONS"):
            # Annotations are visible on the public run page even when logs need sign-in.
            esc = detail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error title=e2e test failed::{esc}")
        sys.exit("e2e test of the packaged binary failed")
    print("e2e tests passed")

    OUT.mkdir(exist_ok=True)
    name = f"mcd-{os_name}-{arch}"
    if os_name == "windows":
        archive = OUT / f"{name}.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted((dist / "mcd").rglob("*")):
                z.write(f, f.relative_to(dist))
    else:
        archive = OUT / f"{name}.tar.gz"
        with tarfile.open(archive, "w:gz") as t:
            t.add(dist / "mcd", arcname="mcd")
    print(f"built {archive} ({archive.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
