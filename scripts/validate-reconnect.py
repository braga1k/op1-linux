#!/usr/bin/env python3
"""Interactive USB reconnect test, with automatic restoration of the original profile."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from op1.protocol import Hidraw, Mouse, discover
from op1.backups import save_backup

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("--run", action="store_true")
p.add_argument("--seconds", type=int, default=600)
p.add_argument("--output", type=Path, default=Path("validation/reconnect.json"))
a = p.parse_args()
if not a.run:
    p.error("--run is required")
paths = discover()
if len(paths) != 1:
    p.error("Connect exactly one OP1.")


def identity(path):
    return os.path.realpath("/sys/class/hidraw/" + path.name)


def read():
    h = Hidraw(discover()[0])
    try:
        return Mouse(h).read()
    finally:
        h.close()


original = read()
backup = save_backup(original, a.output.parent / "backups")
start_id = identity(paths[0])
rate = 1000 if original[21] != 8 else 2000
h = Hidraw(paths[0])
try:
    desired = Mouse(h).apply(original, {"polling": rate}, a.output.parent / "backups")
finally:
    h.close()
result = {
    "kind": "physical-usb-reconnect",
    "test_polling_hz": rate,
    "original_backup": str(backup),
    "original_hex": original.hex(),
    "written_hex": desired.hex(),
    "disconnect_observed": False,
    "reconnect_observed": False,
}
a.output.write_text(json.dumps(result, indent=2))
print(
    "READY: unplug and reconnect the OP1. Original profile will then be restored.",
    flush=True,
)
try:
    end = time.monotonic() + a.seconds
    while time.monotonic() < end:
        paths = discover()
        if not paths:
            result["disconnect_observed"] = True
        elif identity(paths[0]) != start_id:
            result["reconnect_observed"] = True
            time.sleep(1)
            current = read()
            result["after_reconnect_hex"] = current.hex()
            result["full_payload_persisted"] = current[16:1040] == desired[16:1040]
            break
        time.sleep(0.03)
finally:
    if discover():
        current = read()
        h = Hidraw(discover()[0])
        try:
            restored = Mouse(h).restore(current, original, a.output.parent / "backups")
        finally:
            h.close()
        result["original_restored"] = restored[16:1040] == original[16:1040]
    else:
        result["original_restored"] = False
    a.output.write_text(json.dumps(result, indent=2))
    print(
        json.dumps({k: v for k, v in result.items() if not k.endswith("hex")}),
        flush=True,
    )
