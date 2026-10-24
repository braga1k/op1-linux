"""Falhas transacionais, integridade to recuperação; sem acesso a hardware."""

import errno
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch as mock

from op1.protocol import (
    Mouse,
    ProtocolError,
    WriteUncertain,
    demo_blob,
    patch,
    restore_profile,
)
from op1.backups import save_backup, load_backup, default_directory
from op1.__main__ import error_result, execute
from test_protocol import Fake


class Transactions(unittest.TestCase):
    def test_unexpected_corruption_is_not_reported_as_success(self):
        f = Fake()
        f.corrupt = True
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(WriteUncertain) as result:
                Mouse(f, sleep=lambda _: None).apply(
                    demo_blob(), {"polling": 1000}, Path(t)
                )
            blob, _ = load_backup(Path(result.exception.backup))
            self.assertEqual(blob, demo_blob())
            self.assertEqual(
                error_result(result.exception, "apply")["code"], "write_uncertain"
            )

    def test_disconnect_at_write_keeps_durable_backup_and_uncertain_state(self):
        class Disconnected(Fake):
            def send(self, report):
                if report[0] == 0xA0:
                    raise OSError(errno.ENODEV, "desligado")
                super().send(report)

        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(WriteUncertain) as result:
                Mouse(Disconnected(), sleep=lambda _: None).apply(
                    demo_blob(), {"polling": 1000}, Path(t)
                )
            self.assertTrue(Path(result.exception.backup).exists())

    def test_backup_failure_prevents_write(self):
        f = Fake()
        with mock(
            "op1.backups.save_backup", side_effect=OSError(errno.ENOSPC, "sem espaço")
        ):
            with self.assertRaises(OSError):
                Mouse(f, sleep=lambda _: None).apply(
                    demo_blob(), {"polling": 1000}, Path("/unused")
                )
        self.assertFalse(any(x[0] == 0xA0 for x in f.sent))

    def test_unknown_firmware_never_writes(self):
        f = Fake()
        f.firmware = (8, 1)
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ProtocolError):
                Mouse(f, sleep=lambda _: None).apply(
                    demo_blob(), {"polling": 1000}, Path(t)
                )
            self.assertEqual(list(Path(t).iterdir()), [])
        self.assertEqual(len(f.sent), 1)

    def test_busy_exhaustion_is_bounded(self):
        f = Fake()
        f.busy = 99
        sleeps = []
        with self.assertRaises(ProtocolError):
            Mouse(f, sleep=sleeps.append).read()
        self.assertEqual(len(sleeps), 6)
        self.assertFalse(any(x[0] == 0xA0 for x in f.sent))

    def test_restore_reverses_known_changes_and_verifies_every_byte(self):
        saved = demo_blob()
        changed = patch(
            saved,
            {"polling": 1000, "stages": {"0": {"x": 1250, "y": 1250, "split": False}}},
        )
        f = Fake(changed)
        with tempfile.TemporaryDirectory() as t:
            actual = Mouse(f, sleep=lambda _: None).restore(changed, saved, Path(t))
            self.assertEqual(actual[16:1040], saved[16:1040])
            backup, _ = load_backup(next(Path(t).glob("*.json")))
            self.assertEqual(backup, changed)

    def test_restore_rejects_unmanaged_or_custom_new_fields(self):
        saved = bytearray(demo_blob())
        saved[400] = 7
        with self.assertRaises(ProtocolError):
            restore_profile(demo_blob(), bytes(saved))
        saved = bytearray(demo_blob())
        saved[78:84] = bytes([2, 1, 4, 0, 0, 0])
        with self.assertRaises(ProtocolError):
            restore_profile(demo_blob(), bytes(saved))

    def test_backup_checksum_and_device_identity(self):
        with tempfile.TemporaryDirectory() as t:
            p = save_backup(demo_blob(), Path(t))
            blob, doc = load_backup(p)
            self.assertEqual(blob, demo_blob())
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            doc["report_hex"] = patch(blob, {"polling": 1000}).hex()
            p.write_text(json.dumps(doc))
            with self.assertRaises(ProtocolError):
                load_backup(p)
            doc["vid"] = 0
            p.write_text(json.dumps(doc))
            with self.assertRaises(ProtocolError):
                load_backup(p)

    def test_malformed_backup_variants(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "backup.json"
            for text in ["[]", "{}", "not json", "x" * 65537]:
                p.write_text(text)
                with self.assertRaises(ProtocolError):
                    load_backup(p)

    def test_cli_discovery_and_access_errors(self):
        with mock("op1.__main__.discover", return_value=[]):
            self.assertEqual(execute("read")["code"], "device_missing")
        with mock("op1.__main__.discover", return_value=[Path("/a"), Path("/b")]):
            self.assertEqual(execute("read")["code"], "ambiguous_device")
        with (
            mock("op1.__main__.discover", return_value=[Path("/a")]),
            mock("op1.__main__.Hidraw", side_effect=PermissionError()),
        ):
            self.assertEqual(execute("read")["code"], "permission_denied")
        self.assertEqual(
            error_result(BlockingIOError(), "read")["code"], "device_locked"
        )
        self.assertEqual(
            error_result(OSError(errno.ENODEV, "gone"), "read")["code"], "disconnected"
        )

    def test_noop_restore_cannot_hide_an_external_profile_change(self):
        original = demo_blob()
        changed = patch(original, {"polling": 1000})
        device = Fake(changed)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ProtocolError):
                Mouse(device, sleep=lambda _: None).restore(
                    original, original, Path(folder)
                )
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertFalse(any(frame[0] == 0xA0 for frame in device.sent))

    def test_data_directory_does_not_depend_on_installation_location(self):
        with mock.dict("os.environ", {"XDG_STATE_HOME": "/tmp/test-state"}):
            self.assertEqual(
                default_directory(), Path("/tmp/test-state/op1-linux/backups")
            )


if __name__ == "__main__":
    unittest.main()
