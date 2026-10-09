"""Prepare release files: stamp checksums into the installers and write SHA256SUMS.

    python packaging/stamp.py <release-dir> <version-tag>

The release copies of install.sh / install.ps1 carry the SHA-256 of every package, so an
install never needs to fetch a separate checksum file (that request is what stalls on slow
networks to GitHub). SHA256SUMS is still published for anyone who wants to verify by hand.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"(# @@EMBEDDED_BEGIN@@\n).*?(# @@EMBEDDED_END@@)", re.S)
SAFE = re.compile(r"^[0-9a-f]{64}  [A-Za-z0-9._-]+$")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp(template: str, body: str) -> str:
    out, n = BLOCK.subn(lambda m: m.group(1) + body + m.group(2), template)
    if n != 1:
        sys.exit("embedded block not found exactly once")
    return out


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    rel, version = Path(sys.argv[1]), sys.argv[2]
    if not re.fullmatch(r"v\d+\.\d+\.\d+([.-][0-9A-Za-z.]+)?", version):
        sys.exit(f"unexpected version tag: {version}")
    packages = sorted(p for p in rel.iterdir() if p.name.startswith("mcd-") and p.suffix in (".gz", ".zip"))
    if not packages:
        sys.exit("no packages found")
    lines = [f"{sha256(p)}  {p.name}" for p in packages]
    assert all(SAFE.match(l) for l in lines)
    sums = "\n".join(lines)

    sh = stamp((ROOT / "install.sh").read_text(encoding="utf-8"),
               f'EMBEDDED_VERSION="{version}"\nEMBEDDED_SUMS=\'{sums}\'\n')
    ps = stamp((ROOT / "install.ps1").read_text(encoding="utf-8"),
               f"$EmbeddedVersion = '{version}'\n$EmbeddedSums = @'\n{sums}\n'@\n")
    (rel / "install.sh").write_text(sh, encoding="utf-8", newline="\n")
    (rel / "install.ps1").write_text(ps, encoding="utf-8", newline="\n")

    all_lines = lines + [f"{sha256(rel / n)}  {n}" for n in ("install.sh", "install.ps1")]
    (rel / "SHA256SUMS").write_text("\n".join(all_lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(all_lines))


if __name__ == "__main__":
    main()
