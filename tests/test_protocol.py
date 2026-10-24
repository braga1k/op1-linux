import json
from pathlib import Path
import tempfile
import unittest
from op1.protocol import *


class Fake:
    def __init__(self, blob=None):
        self.blob = blob or demo_blob()
        self.sent = []
        self.busy = 0
        self.ignore = False
        self.short = False
        self.op = None
        self.firmware = (7, 1)
        self.corrupt = False

    def send(self, report):
        self.sent.append(report)
        self.op = report[1]
        if report[0] == 0xA0 and not self.ignore:
            self.blob = report[:1] + b"\x01" + report[2:]
            if self.corrupt:
                b = bytearray(self.blob)
                b[400] ^= 1
                self.blob = bytes(b)

    def get(self, rid, length):
        if self.short:
            return b"\xa0\x01"
        if self.busy:
            self.busy -= 1
            return bytes([rid, 3]) + bytes(length - 2)
        if rid == 0xA0:
            return self.blob
        result = bytearray(bytes([rid, 1]) + bytes(length - 2))
        if self.op == 2:
            result[17:19] = bytes(self.firmware)
        return bytes(result)


class ProtocolTests(unittest.TestCase):
    def test_new_107_bitfields_preserve_each_other_and_upper_bits(self):
        b = bytearray(demo_blob())
        b[27] = 0xB1
        for s in SMOOTHING.values():
            for d in DOWNSHIFT.values():
                out = patch(bytes(b), {"smoothing": s, "downshift": d})
                self.assertEqual(out[27], 0xB0 | s | d)
                self.assertEqual(out[:27], b[:27])
                self.assertEqual(out[28:], b[28:])

    def test_polling_all_seven_dividers(self):
        for hz, divider in RATES.items():
            self.assertEqual(patch(demo_blob(), {"polling": hz})[21], divider)

    def test_quantization_boundaries(self):
        self.assertEqual(
            [quantize_cpi(x) for x in [10, 14, 15, 9999, 10000, 10024, 10025, 29999]],
            [10, 10, 20, 10000, 10000, 10000, 10050, 30000],
        )
        for n in [0, 30001, -10, True, 1.2]:
            with self.assertRaises(ValueError):
                quantize_cpi(n)

    def test_preserve_custom_actions_and_unknown_data(self):
        b = bytearray(demo_blob())
        b[400:405] = b"abcde"
        b[78:84] = bytes([2, 1, 4, 0, 0, 0])
        b[130] = 0xAC
        out = patch(bytes(b), {"polling": 1000, "slam": False})
        self.assertEqual([i for i in range(CFG_LEN) if b[i] != out[i]], [21, 22])

    def test_mapping_filter_alignment(self):
        b = demo_blob()
        out = patch(b, {"buttons": {"Back": "Mute"}, "filters": {"4": 10}})
        self.assertEqual(out[99:105], bytes([32, 226, 0, 0, 0, 0]))
        self.assertEqual(out[105], 10)
        self.assertEqual(out[106:112], b[106:112])
        self.assertEqual(out[71:77], b[71:77])

    def test_left_click_cannot_be_lost(self):
        with self.assertRaises(ValueError):
            patch(demo_blob(), {"buttons": {"Left": "Disable"}})
        out = patch(
            demo_blob(), {"buttons": {"Left": "Right click", "Right": "Left click"}}
        )
        self.assertEqual(out[78:80], b"\0\1")

    def test_read_framing_and_busy(self):
        f = Fake()
        f.busy = 2
        m = Mouse(f, sleep=lambda _: None)
        self.assertEqual(m.read(), demo_blob())
        self.assertEqual(f.sent, [b"\xa1\x12" + bytes(62)])

    def test_reject_short_and_invalid(self):
        f = Fake()
        f.short = True
        with self.assertRaises(ProtocolError):
            Mouse(f, sleep=lambda _: None).read()
        for off, value in [(21, 0), (30, 0), (29, 4), (51, 2)]:
            b = bytearray(demo_blob())
            b[off] = value
            with self.assertRaises(ProtocolError):
                validate(b)

    def test_apply_backup_and_readback(self):
        f = Fake()
        m = Mouse(f, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as t:
            out = m.apply(demo_blob(), {"polling": 1000}, Path(t))
            files = list(Path(t).glob("*.json"))
            self.assertEqual(len(files), 1)
            self.assertEqual(
                json.loads(files[0].read_text())["report_hex"], demo_blob().hex()
            )
            self.assertEqual(out[21], 8)
            self.assertEqual(
                [x[:2] for x in f.sent],
                [b"\xa1\x02", b"\xa1\x12", b"\xa0\x11", b"\xa1\x12"],
            )

    def test_stale_profile_blocks_write(self):
        f = Fake(patch(demo_blob(), {"active": 3}))
        m = Mouse(f, sleep=lambda _: None)
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ProtocolError):
                m.apply(demo_blob(), {"polling": 1000}, Path(t))
            self.assertFalse(list(Path(t).iterdir()))
            self.assertEqual(len(f.sent), 2)

    def test_readback_mismatch_is_error_and_backup_remains(self):
        f = Fake()
        f.ignore = True
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ProtocolError):
                Mouse(f, sleep=lambda _: None).apply(
                    demo_blob(), {"polling": 1000}, Path(t)
                )
            self.assertEqual(len(list(Path(t).glob("*.json"))), 1)

    def test_noop_reads_without_writing_or_backing_up(self):
        f = Fake()
        with tempfile.TemporaryDirectory() as t:
            Mouse(f, sleep=lambda _: None).apply(demo_blob(), {}, Path(t))
            self.assertEqual(list(Path(t).iterdir()), [])
        self.assertEqual(f.sent, [b"\xa1\x12" + bytes(62)])

    def test_cpi_stage_requires_consistency(self):
        with self.assertRaises(ValueError):
            patch(demo_blob(), {"count": 1})
        out = patch(
            demo_blob(),
            {
                "count": 1,
                "active": 1,
                "stages": {"0": {"split": False, "x": 805, "y": 1600}},
            },
        )
        self.assertEqual(decode(out)["stages"][0], {"split": False, "x": 810, "y": 810})

    def test_captured_hardware_frames(self):
        for name, rid, length in [
            ("hardware-frame", 0xA0, 1041),
            ("hardware-version-frame", 0xA1, 64),
        ]:
            fixture = json.loads((Path(__file__).parent / (name + ".json")).read_text())
            raw = bytes.fromhex(fixture["buffer_hex"])[: fixture["length"]]
            result = normalize_frame(raw, rid, length)
            self.assertEqual(len(result), length)
            self.assertEqual(result[1 : len(raw)], raw[1:])
            if rid == 0xA0:
                state = decode(result)
                self.assertEqual(state["polling"], 8000)
                self.assertEqual(state["stages"][0]["x"], 1600)
                self.assertEqual(state["filters"][0], 240)
            with self.assertRaises(ProtocolError):
                normalize_frame(raw[:-1], rid, length)

    def test_ioctl_values_match_linux_header(self):
        self.assertEqual(ioctl_code(6, 64), 0xC0404806)
        self.assertEqual(ioctl_code(7, 1041), 0xC4114807)
        self.assertEqual(ioctl_code(3, 8, 2), 0x80084803)


if __name__ == "__main__":
    unittest.main()
