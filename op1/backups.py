"""Durable, identified and verifiable OP1 profile backups."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .protocol import VID, PID, validate, decode, ProtocolError


def default_directory():
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "op1-linux" / "backups"


def payload_digest(blob):
    return hashlib.sha256(blob[16:1040]).hexdigest()


def save_backup(blob: bytes, folder: Path, firmware="1.07") -> Path:
    validate(blob)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    document = {
        "format": "op1-linux-backup-v2",
        "vid": VID,
        "pid": PID,
        "firmware": firmware,
        "created_utc": stamp,
        "report_hex": blob.hex(),
        "payload_sha256": payload_digest(blob),
        "settings": decode(blob),
    }
    # Temp + fsync + rename: a partial file is never offered as a valid backup.
    fd, temporary = tempfile.mkstemp(prefix=".op1-", dir=folder)
    path = folder / f"op1-{stamp}.json"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def load_backup(path: Path) -> tuple[bytes, dict]:
    try:
        with Path(path).open("rb") as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError("file is too large")
        document = json.loads(data)
        if not isinstance(document, dict):
            raise ValueError("invalid document")
        if document.get("format") not in ("op1-linux-backup-v1", "op1-linux-backup-v2"):
            raise ValueError("unknown format")
        if (type(document.get("vid")), type(document.get("pid"))) != (int, int) or (
            document["vid"],
            document["pid"],
        ) != (VID, PID):
            raise ValueError("different mouse model")
        blob = bytes.fromhex(document["report_hex"])
        validate(blob)
        if document["format"].endswith("v2"):
            if document.get("firmware") != "1.07":
                raise ValueError("unsupported firmware")
            if document.get("payload_sha256") != payload_digest(blob):
                raise ValueError("integrity check failed")
        # v1 contains no checksum: shown explicitly in the preview, never trusted as code.
        return blob, document
    except (OSError, ValueError, KeyError, TypeError, ProtocolError) as error:
        raise ProtocolError(f"Invalid backup: {error}") from error
