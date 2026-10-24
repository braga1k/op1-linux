#!/usr/bin/env python3
"""Captura apenas transferências HID feature A0/A1 do OP1, não tráfego de teclado."""

import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import time

p = argparse.ArgumentParser()
p.add_argument("output")
p.add_argument("--seconds", type=int, default=180)
a = p.parse_args()
root = Path("/sys/bus/usb/devices")
devices = []
for d in root.iterdir():
    try:
        if (d / "idVendor").read_text().strip() == "3367" and (
            d / "idProduct"
        ).read_text().strip() == "1978":
            devices.append(d)
    except OSError:
        pass
if len(devices) != 1:
    raise SystemExit("É necessário exatamente um OP1 8k v2.")
d = devices[0]
bus = int((d / "busnum").read_text())
dev = int((d / "devnum").read_text())
subprocess.run(["/usr/bin/modprobe", "usbmon"], check=True)
source = Path(f"/sys/kernel/debug/usb/usbmon/{bus}u")
# Linux usbmon text starts with an URB tag. Keep only vendor feature requests
# and their completions, identified by setup report IDs (no mouse input packets).
fd = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
end = time.monotonic() + a.seconds
pending = set()
buffer = b""
count = 0
output = Path(a.output)
try:
    with output.open("x") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": "capture",
                    "source": "usbmon",
                    "bus": bus,
                    "device": dev,
                    "vid": "3367",
                    "pid": "1978",
                    "duration_limit": a.seconds,
                }
            )
            + "\n"
        )
        stream.flush()
        while time.monotonic() < end:
            if Path(str(output) + ".stop").exists():
                break
            if not select.select([fd], [], [], 0.25)[0]:
                continue
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                continue
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                text = line.decode("ascii", "replace")
                parts = text.split()
                if len(parts) < 4:
                    continue
                addr = parts[3].split(":")
                if len(addr) != 4 or addr[0] not in ("Ci", "Co"):
                    continue
                try:
                    match = int(addr[1]) == bus and int(addr[2]) == dev
                except ValueError:
                    continue
                if not match:
                    continue
                tag = parts[0]
                event = parts[2]
                if (
                    event == "S"
                    and len(parts) > 8
                    and parts[4] == "s"
                    and parts[5:7] in (["a1", "01"], ["21", "09"])
                    and parts[7].lower() in ("03a0", "03a1")
                ):
                    pending.add(tag)
                elif tag not in pending:
                    continue
                if tag in pending:
                    stream.write(json.dumps({"kind": "urb", "line": text}) + "\n")
                    stream.flush()
                    count += 1
                    if event in ("C", "E"):
                        pending.discard(tag)
        stream.write(json.dumps({"kind": "end", "urb_lines": count}) + "\n")
finally:
    os.close(fd)
    if "PKEXEC_UID" in os.environ:
        uid = int(os.environ["PKEXEC_UID"])
        os.chown(output, uid, -1)
print(f"{count} linhas URB OP1 guardadas em {output}")
