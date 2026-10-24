"""Protocolo HID; offsets confirmados no configurador 1.07 via REA/Ghidra.
Referência adicional: qsxcv/UnofficialEGGWebConfig (AGPL-3.0).
"""

from __future__ import annotations
import fcntl
import os
from pathlib import Path
import struct
import time

VID, PID = 0x3367, 0x1978
CFG_LEN, CMD_LEN = 1041, 64
RATES = {125: 64, 250: 32, 500: 16, 1000: 8, 2000: 4, 4000: 2, 8000: 1}
SMOOTHING = {"Force off": 2, "Ripple Control off": 0, "Ripple Control on": 1}
DOWNSHIFT = {
    "Force off": 8,
    "Light timer only": 12,
    "Medium timer only": 4,
    "PixArt default": 0,
}
BOOL_FIELDS = {"angle_snap": 26, "motion_sync": 28, "max_fps": 129}
ACTION_SLOTS = {
    "Left": 71,
    "Right": 78,
    "Middle": 85,
    "Forward": 92,
    "Back": 99,
    "Wheel up": 113,
    "Wheel down": 120,
}
ACTIONS = {
    "Left click": (0, 1),
    "Right click": (0, 2),
    "Middle click": (0, 4),
    "Back": (0, 8),
    "Forward": (0, 16),
    "Scroll up": (1, 1),
    "Scroll down": (1, 255),
    "Cycle CPI": (9, 241),
    "Play / pause": (32, 205),
    "Next track": (32, 181),
    "Previous track": (32, 182),
    "Mute": (32, 226),
    "Volume up": (32, 233),
    "Volume down": (32, 234),
    "Disable": (255, 0),
}


class ProtocolError(Exception):
    """Falha anterior à escrita ou relatório recusado."""


class WriteUncertain(ProtocolError):
    """A write was attempted; the final device state is unconfirmed."""

    def __init__(self, message, backup):
        self.backup = str(backup)
        super().__init__(
            f"{message} The mouse state is unconfirmed. Read the mouse again. Previous profile: {backup}"
        )


def vendor_descriptor(data: bytes) -> bool:
    return (
        b"\x06\x01\xff\x09\x02" in data and b"\x85\xa0" in data and b"\x85\xa1" in data
    )


def ioctl_code(number: int, size: int, direction: int = 3) -> int:
    return (direction << 30) | (size << 16) | (ord("H") << 8) | number


def normalize_frame(data: bytes, report_id: int, length: int) -> bytes:
    # OP1 FW 1.07 returns an embedded header in a payload-sized transfer:
    # A0: 1040 bytes, [0]=00, [1]=status; all 1024 payload bytes are present.
    # A1: 63 bytes, [0]=A1, [1]=status. The extra Windows byte is padding.
    # This exact shape was captured on the user's mouse; never shift offsets.
    if len(data) == length - 1 and (report_id, length) in (
        (0xA0, CFG_LEN),
        (0xA1, CMD_LEN),
    ):
        allowed_ids = (0, 0xA0, 0xA1) if report_id == 0xA0 else (0xA1,)
        if data[0] in allowed_ids and data[1] in (1, 3):
            return bytes([report_id]) + data[1:] + b"\0"
    if len(data) == length and data[0] == report_id:
        return data
    raise ProtocolError(
        f"Unsupported HID response: {len(data)}/{length} bytes. No profile will be applied."
    )


def discover(sysroot: Path = Path("/sys/class/hidraw")) -> list[Path]:
    found = []
    for entry in sorted(sysroot.glob("hidraw*")):
        try:
            info = dict(
                line.split("=", 1)
                for line in (entry / "device/uevent").read_text().splitlines()
                if "=" in line
            )
            if info.get("HID_ID", "").upper() != "0003:00003367:00001978":
                continue
            desc = (entry / "device/report_descriptor").read_bytes()
            if vendor_descriptor(desc):
                found.append(Path("/dev") / entry.name)
        except (OSError, ValueError):
            continue
    return found


class Hidraw:
    def __init__(self, path: Path):
        self.fd = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            info = bytearray(8)
            fcntl.ioctl(self.fd, ioctl_code(3, 8, 2), info, True)
            bus, vid, pid = struct.unpack("IHH", info)
            if (bus, vid, pid) != (3, VID, PID):
                raise ProtocolError("The selected device is not an OP1 8k v2.")
            size = bytearray(4)
            fcntl.ioctl(self.fd, ioctl_code(1, 4, 2), size, True)
            count = struct.unpack("I", size)[0]
            if not 1 <= count <= 4096:
                raise ProtocolError("Invalid HID descriptor.")
            descriptor = bytearray(4100)
            struct.pack_into("I", descriptor, 0, count)
            fcntl.ioctl(self.fd, ioctl_code(2, 4100, 2), descriptor, True)
            if not vendor_descriptor(bytes(descriptor[4 : 4 + count])):
                raise ProtocolError("This is not the OP1 configuration interface.")
            # Cross-process lock on this hidraw inode; never detach the kernel driver.
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    def send(self, report: bytes):
        result = fcntl.ioctl(
            self.fd, ioctl_code(6, len(report)), bytearray(report), True
        )
        if result != len(report):
            raise ProtocolError(f"Incomplete HID write: {result}/{len(report)} bytes.")

    def get(self, report_id: int, length: int) -> bytes:
        buf = bytearray(length)
        buf[0] = report_id
        result = fcntl.ioctl(self.fd, ioctl_code(7, length), buf, True)
        return normalize_frame(bytes(buf[:result]), report_id, length)


def validate(blob: bytes):
    if len(blob) != CFG_LEN or blob[0] != 0xA0 or blob[1] != 1:
        raise ProtocolError("Invalid configuration response.")
    if blob[21] not in RATES.values() or not 1 <= blob[30] <= 4 or blob[29] >= blob[30]:
        raise ProtocolError("Unsupported profile: invalid polling rate or CPI levels.")
    for n in range(blob[30]):
        split, x, y = struct.unpack_from("<BHH", blob, 51 + 5 * n)
        if split not in (0, 1) or not 10 <= x <= 30000 or not 10 <= y <= 30000:
            raise ProtocolError("Unsupported profile: invalid CPI values.")


def quantize_cpi(value: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 10 <= value <= 30000
    ):
        raise ValueError("CPI must be a whole number from 10 to 30000.")
    step = 10 if value <= 10000 else 50
    return min(30000, ((value + step // 2) // step) * step)


def decode(blob: bytes) -> dict:
    validate(blob)
    state = {
        "polling": 8000 // blob[21],
        "count": blob[30],
        "active": blob[29] + 1,
        "lod": blob[25],
        "angle": struct.unpack_from("b", blob, 128)[0],
        "slam": bool(blob[22] & 1),
        "jitter": bool(blob[22] & 16),
        "led_liftoff": blob[24] == 0,
        "smoothing": blob[27] & 3,
        "downshift": blob[27] & 12,
        "glass": blob[127],
        "stages": [],
        "buttons": {},
        "filters": [],
    }
    for key, offset in BOOL_FIELDS.items():
        state[key] = bool(blob[offset])
    for n in range(4):
        split, x, y = struct.unpack_from("<BHH", blob, 51 + 5 * n)
        state["stages"].append({"split": bool(split), "x": x, "y": y})
    for name, offset in ACTION_SLOTS.items():
        raw = blob[offset : offset + 6]
        state["buttons"][name] = next(
            (label for label, pair in ACTIONS.items() if raw == bytes(pair) + bytes(4)),
            "Custom (keep unchanged)",
        )
    state["filters"] = [blob[77 + 7 * n] for n in range(5)]
    return state


def patch(blob: bytes, changes: dict) -> bytes:
    """Alterar apenas campos pedidos; preservar bytes unknowns to ações personalizadas."""
    validate(blob)
    out = bytearray(blob)
    allowed = set(BOOL_FIELDS) | {
        "polling",
        "count",
        "active",
        "lod",
        "angle",
        "slam",
        "jitter",
        "led_liftoff",
        "smoothing",
        "downshift",
        "stages",
        "buttons",
        "filters",
    }
    if set(changes) - allowed:
        raise ValueError("Unknown fields: " + ", ".join(sorted(set(changes) - allowed)))

    def integer(key, low, high):
        v = changes[key]
        if isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high:
            raise ValueError(f"{key}: choose a value from {low} to {high}.")
        return v

    if "polling" in changes:
        v = integer("polling", 125, 8000)
        if v not in RATES:
            raise ValueError("Invalid polling rate.")
        if blob[127] != 0:
            raise ValueError(
                "Glass Mode is enabled: changing the polling rate is unsupported."
            )
        out[21] = RATES[v]
    for key, off, low, high in [
        ("count", 30, 1, 4),
        ("lod", 25, 0, 10),
        ("angle", 128, -127, 127),
    ]:
        if key in changes:
            if key == "lod" and blob[127] != 0:
                raise ValueError(
                    "Glass Mode is enabled: changing lift-off distance is unsupported."
                )
            out[off] = integer(key, low, high) & 255
    if "active" in changes:
        out[29] = integer("active", 1, 4) - 1
    if out[29] >= out[30]:
        raise ValueError("The active level must be within the enabled CPI levels.")
    for key, off in BOOL_FIELDS.items():
        if key in changes:
            if type(changes[key]) is not bool:
                raise ValueError(f"{key}: expected true or false.")
            out[off] = int(changes[key])
    for key, bit in [("slam", 1), ("jitter", 16)]:
        if key in changes:
            if type(changes[key]) is not bool:
                raise ValueError(f"{key}: expected true or false.")
            out[22] = (out[22] & ~bit) | (bit if changes[key] else 0)
    if "led_liftoff" in changes:
        if type(changes["led_liftoff"]) is not bool:
            raise ValueError("LED: expected true or false.")
        out[24] = int(not changes["led_liftoff"])
    for key, mask, values in [
        ("smoothing", 3, SMOOTHING.values()),
        ("downshift", 12, DOWNSHIFT.values()),
    ]:
        if key in changes:
            v = integer(key, 0, 15)
            if v not in values:
                raise ValueError("Invalid sensor option.")
            out[27] = (out[27] & ~mask) | v
    for group in ("stages", "buttons", "filters"):
        if group in changes and not isinstance(changes[group], dict):
            raise ValueError(f"{group}: expected a set of changes.")
    for index, stage in changes.get("stages", {}).items():
        n = int(index)
        if n not in range(4) or str(n) != str(index):
            raise ValueError("Invalid CPI level.")
        if not isinstance(stage, dict) or set(stage) != {"x", "y", "split"}:
            raise ValueError("Incomplete CPI level.")
        x, y = quantize_cpi(stage["x"]), quantize_cpi(stage["y"])
        split = stage["split"]
        if type(split) is not bool:
            raise ValueError("Invalid X/Y setting.")
        struct.pack_into("<BHH", out, 51 + 5 * n, int(split), x, y if split else x)
    for name, action in changes.get("buttons", {}).items():
        if name not in ACTION_SLOTS or action not in ACTIONS:
            raise ValueError("Invalid button action.")
        offset = ACTION_SLOTS[name]
        out[offset : offset + 6] = bytes(ACTIONS[action]) + bytes(4)
    if "buttons" in changes and not any(
        out[o : o + 6] == bytes([0, 1, 0, 0, 0, 0])
        for o in list(ACTION_SLOTS.values())[:5]
    ):
        raise ValueError("Keep Left click assigned to at least one physical button.")
    for index, value in changes.get("filters", {}).items():
        n = int(index)
        if (
            str(n) != str(index)
            or n not in range(5)
            or type(value) is not int
            or (value not in range(26) and not (n < 2 and value in (240, 241)))
        ):
            raise ValueError("Invalid multiclick filter or GX mode.")
        out[77 + 7 * n] = value
    validate(out)
    return bytes(out)


class Mouse:
    def __init__(self, transport, sleep=time.sleep):
        self.transport, self.sleep = transport, sleep

    def command(self, opcode: int):
        self.transport.send(bytes([0xA1, opcode]) + bytes(CMD_LEN - 2))

    def response(self, report_id: int, length: int) -> bytes:
        for attempt in range(5):
            blob = self.transport.get(report_id, length)
            if len(blob) != length or blob[0] != report_id:
                raise ProtocolError("Unexpected HID length or report ID.")
            if blob[1] == 1:
                return blob
            if blob[1] != 3:
                raise ProtocolError(f"The mouse returned status 0x{blob[1]:02x}.")
            self.sleep(0.1 * (attempt + 1))
        raise ProtocolError("The mouse is still busy. Try reading it again.")

    def read(self) -> bytes:
        self.command(0x12)
        self.sleep(0.08)
        blob = self.response(0xA0, CFG_LEN)
        validate(blob)
        return blob

    def version(self) -> str:
        self.command(2)
        self.sleep(0.05)
        response = self.response(0xA1, CMD_LEN)
        patch_version, major = response[17:19]
        return (
            f"{major}.{patch_version:02}"
            if 1 <= major <= 9 and patch_version <= 99
            else "unknown"
        )

    def apply(self, baseline: bytes, changes: dict, backup_dir: Path) -> bytes:
        desired = patch(baseline, changes)
        return self.commit(baseline, desired, backup_dir)

    def commit(self, baseline: bytes, desired: bytes, backup_dir: Path) -> bytes:
        from .backups import save_backup

        validate(baseline)
        validate(desired)
        if desired[16:1040] == baseline[16:1040]:
            current = self.read()
            if current[16:1040] != baseline[16:1040]:
                raise ProtocolError(
                    "The profile changed on the mouse. Read it again before applying."
                )
            return current
        firmware = self.version()
        if firmware != "1.07":
            raise ProtocolError(
                f"Firmware {firmware}: writing is not validated. Firmware 1.07 is required."
            )
        current = self.read()
        if current[16:1040] != baseline[16:1040]:
            raise ProtocolError(
                "The profile changed on the mouse. Read it again before applying."
            )
        backup = save_backup(current, backup_dir, firmware)
        self.last_backup = str(backup)
        report = bytearray(desired)
        report[0:16] = bytes([0xA0, 0x11]) + bytes(14)
        try:
            # No automatic resend: a failed ioctl can still have reached the mouse.
            self.transport.send(bytes(report))
            self.sleep(0.3)
            self.response(0xA1, CMD_LEN)
            actual = self.read()
            if actual[16:1040] != desired[16:1040]:
                offsets = [n for n in range(16, 1040) if actual[n] != desired[n]]
                raise ProtocolError(
                    "Read-back differs from the requested profile at offsets "
                    + str(offsets[:16])
                    + "."
                )
            return actual
        except (OSError, ProtocolError) as error:
            raise WriteUncertain(str(error), backup) from error

    def restore(self, baseline: bytes, saved: bytes, backup_dir: Path) -> bytes:
        """Restore understood fields; refuse changes to unmanaged bytes."""
        desired = restore_profile(baseline, saved)
        return self.commit(baseline, desired, backup_dir)


def restore_profile(current: bytes, saved: bytes) -> bytes:
    validate(current)
    validate(saved)
    before, target = decode(current), decode(saved)
    changes = {}
    for key in [
        *BOOL_FIELDS,
        "polling",
        "count",
        "active",
        "lod",
        "angle",
        "slam",
        "jitter",
        "led_liftoff",
        "smoothing",
        "downshift",
    ]:
        if before[key] != target[key]:
            changes[key] = target[key]
    changes["stages"] = {
        str(n): v for n, v in enumerate(target["stages"]) if v != before["stages"][n]
    }
    changes["filters"] = {
        str(n): v for n, v in enumerate(target["filters"]) if v != before["filters"][n]
    }
    # Existing arbitrary key bindings may be restored only byte-for-byte when they
    # already match. New assignments must be one of the understood actions.
    changes["buttons"] = {}
    for name, offset in ACTION_SLOTS.items():
        if current[offset : offset + 6] != saved[offset : offset + 6]:
            action = target["buttons"][name]
            if action not in ACTIONS:
                raise ProtocolError(
                    "The backup contains a different custom action. Restore was refused to preserve the buttons."
                )
            changes["buttons"][name] = action
    if not changes["buttons"]:
        del changes["buttons"]
    desired = patch(current, changes)
    if desired[16:1040] != saved[16:1040]:
        raise ProtocolError(
            "The backup differs in fields this version does not manage. Nothing was written."
        )
    return desired


def save_backup(blob, folder, firmware="1.07"):
    # Compatibility entry point for the original preview's scripts.
    from .backups import save_backup as save

    return save(blob, folder, firmware)


def demo_blob() -> bytes:
    b = bytearray(CFG_LEN)
    b[0:2] = bytes([0xA0, 1])
    b[21] = 1
    b[22] = 1
    b[24] = 1
    b[25] = 3
    b[29] = 1
    b[30] = 4
    b[129] = 1
    for i, cpi in enumerate([400, 800, 1600, 3200]):
        struct.pack_into("<BHH", b, 51 + 5 * i, 0, cpi, cpi)
    for name, action in zip(
        ACTION_SLOTS,
        [
            "Left click",
            "Right click",
            "Middle click",
            "Forward",
            "Back",
            "Scroll up",
            "Scroll down",
        ],
    ):
        off = ACTION_SLOTS[name]
        b[off : off + 6] = bytes(ACTIONS[action]) + bytes(4)
    for n in range(5):
        b[77 + 7 * n] = 8
    return bytes(b)
