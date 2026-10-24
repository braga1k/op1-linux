#!/usr/bin/env python3
"""Build a deterministic source/runtime archive from an explicit allowlist."""

import gzip
import hashlib
import io
from pathlib import Path
import tarfile
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from op1 import __version__

FILES = [
    "README.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "PROTOCOLO.md",
    "install.sh",
    "install-access.sh",
    "run.sh",
    ".ruff.toml",
]
FOLDERS = ["op1", "packaging", "docs", "tests", "scripts", ".github"]
EPOCH = 1792836000


def build(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"op1-linux-{__version__}.tar.gz"
    sources = [ROOT / name for name in FILES]
    for name in FOLDERS:
        sources.extend(
            p
            for p in (ROOT / name).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )
    with (
        output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=EPOCH) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for path in sorted(set(sources)):
            data = path.read_bytes()
            name = f"op1-linux-{__version__}/" + str(path.relative_to(ROOT))
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            entry.mtime = EPOCH
            entry.uid = entry.gid = 0
            entry.uname = entry.gname = ""
            entry.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            archive.addfile(entry, io.BytesIO(data))
    digest = hashlib.file_digest(output.open("rb"), "sha256").hexdigest()
    (destination / "SHA256SUMS").write_text(f"{digest}  {output.name}\n")
    print(output, digest)
    return output


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else ROOT / "dist")
