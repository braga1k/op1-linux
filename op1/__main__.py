"""Entrada CLI to worker isolado utilizado pela interface."""

import argparse
import errno
import json
from pathlib import Path
import signal
import sys

from . import __version__
from .protocol import Hidraw, Mouse, discover, decode, WriteUncertain, ProtocolError
from .backups import default_directory, save_backup, load_backup


def error_result(error, operation, device=None):
    if isinstance(error, WriteUncertain):
        return {
            "error": str(error),
            "code": "write_uncertain",
            "backup": error.backup,
            "uncertain": True,
        }
    if isinstance(error, PermissionError):
        return {
            "error": f"Cannot access the mouse ({device or 'HID'}). Install the included OP1 access rule and reconnect the mouse.",
            "code": "permission_denied",
        }
    if isinstance(error, BlockingIOError):
        return {
            "error": "Another configurator is using the mouse. Close it and try again.",
            "code": "device_locked",
        }
    if isinstance(error, OSError) and error.errno in (
        errno.ENODEV,
        errno.ENOENT,
        errno.ENXIO,
        errno.EIO,
    ):
        return {
            "error": "The mouse was disconnected or stopped responding. Reconnect it and read the profile again.",
            "code": "disconnected",
        }
    if isinstance(error, TimeoutError):
        return {
            "error": "The read timed out. Reconnect the mouse and try again.",
            "code": "timeout",
        }
    return {
        "error": str(error),
        "code": "invalid_profile"
        if isinstance(error, (ValueError, KeyError, TypeError))
        else "communication_failed",
    }


def execute(operation, request=None, *, backup_dir=None):
    transport = None
    device = None
    try:
        paths = discover()
        if not paths:
            return {
                "error": "OP1 8k v2 not found. Connect the mouse by USB.",
                "code": "device_missing",
            }
        if len(paths) != 1:
            return {
                "error": "More than one OP1 was found. Connect only the mouse you want to configure.",
                "code": "ambiguous_device",
            }
        device = paths[0]
        transport = Hidraw(device)
        mouse = Mouse(transport)
        folder = Path(backup_dir) if backup_dir else default_directory()
        request = request or {}
        if operation in ("apply", "restore"):
            baseline = bytes.fromhex(request["baseline"])
            if operation == "apply":
                blob = mouse.apply(baseline, request["changes"], folder)
            else:
                saved, _ = load_backup(Path(request["path"]))
                blob = mouse.restore(baseline, saved, folder)
        else:
            blob = mouse.read()
        out = {
            "report_hex": blob.hex(),
            "settings": decode(blob),
            "device": str(device),
        }
        # Every successful operation reports version; an unavailable version allows
        # reading/backups, but commit itself refuses an unvalidated firmware.
        try:
            out["firmware"] = mouse.version()
        except (OSError, ProtocolError):
            out["firmware"] = "unavailable"
        out["writable"] = out["firmware"] == "1.07"
        if operation == "backup":
            out["backup"] = str(save_backup(blob, folder, out["firmware"]))
        elif getattr(mouse, "last_backup", None):
            out["backup"] = mouse.last_backup
        return out
    except Exception as error:
        return error_result(error, operation, device)
    finally:
        if transport:
            try:
                transport.close()
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(
        description="OP1 8k v2 — unofficial Linux configurator"
    )
    parser.add_argument("--version", action="version", version=__version__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--demo", action="store_true", help="Open a demo without USB access"
    )
    group.add_argument("--list", action="store_true", help="List compatible interfaces")
    group.add_argument(
        "--read", action="store_true", help="Read the current profile as JSON"
    )
    group.add_argument(
        "--backup", action="store_true", help="Back up the current mouse profile"
    )
    group.add_argument(
        "--worker",
        choices=["read", "apply", "backup", "restore"],
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.smoke and not args.demo:
        parser.error("--smoke requires --demo")
    if args.list:
        print(json.dumps([str(p) for p in discover()]))
        return 0
    operation = args.worker or (
        "read" if args.read else "backup" if args.backup else None
    )
    if operation:

        def deadline(*_):
            raise TimeoutError("Communication timed out.")

        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(12)
        try:
            request = (
                json.load(sys.stdin) if operation in ("apply", "restore") else None
            )
            result = execute(operation, request)
        except Exception as error:
            result = error_result(error, operation)
        finally:
            signal.alarm(0)
        print(json.dumps(result, ensure_ascii=False))
        return int("error" in result)
    try:
        from .gui import App
    except (ImportError, ValueError) as error:
        print(
            "Could not load GTK 4/PyGObject. See the runtime dependencies in the README.\n"
            + str(error),
            file=sys.stderr,
        )
        return 1
    app = App(demo=args.demo, smoke=args.smoke)
    code = app.run([])
    return (
        1
        if getattr(app, "smoke_failed", False) or not getattr(app, "ui_ready", False)
        else code
    )


if __name__ == "__main__":
    sys.exit(main())
