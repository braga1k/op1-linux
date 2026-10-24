"""Differential assertions against actual writes from the vendor executable."""

import json
from pathlib import Path
import unittest
from op1.protocol import patch


class VendorGoldens(unittest.TestCase):
    def test_native_serialization_matches_captured_vendor_reports(self):
        fixture = json.loads(
            (Path(__file__).parent / "official-goldens.json").read_text()
        )
        self.assertEqual(len(fixture["cases"]), 15)
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                before = bytes.fromhex(case["before_hex"])
                desired = bytearray(patch(before, case["changes"]))
                desired[:16] = bytes([0xA0, 0x11]) + bytes(14)
                official = bytes.fromhex(case["official_set_hex"])
                self.assertEqual(bytes(desired), official)
                self.assertEqual(
                    desired[16:1040], bytes.fromhex(case["after_hex"])[16:1040]
                )


if __name__ == "__main__":
    unittest.main()
