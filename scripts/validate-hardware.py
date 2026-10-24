#!/usr/bin/env python3
"""Explicitly invoked live-device validation. Never run automatically in CI.

Changes one managed setting per case, backs up and restores the initial profile.
Only tests configuration acceptance/read-back; physical effects need separate evidence.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from op1.protocol import (
    Mouse,
    Hidraw,
    discover,
    decode,
    patch,
    RATES,
    SMOOTHING,
    DOWNSHIFT,
)
from op1.backups import save_backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        action="store_true",
        help="Explicitly enable writes to the attached mouse",
    )
    parser.add_argument(
        "--output", type=Path, default=Path("validation/native-hardware.json")
    )
    args = parser.parse_args()
    if not args.run:
        parser.error(
            "--run is required: this test temporarily changes the mouse profile"
        )
    paths = discover()
    if len(paths) != 1:
        parser.error("Connect exactly one OP1 8k v2.")
    transport = Hidraw(paths[0])
    mouse = Mouse(transport)
    report = {
        "kind": "native-configuration-readback",
        "physical_effects_verified": False,
        "cases": [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    folder = args.output.parent / "backups"
    baseline = mouse.read()
    report["original_backup"] = str(save_backup(baseline, folder))
    report["original_hex"] = baseline.hex()
    report["firmware"] = mouse.version()
    state = decode(baseline)
    cases = [(f"polling-{v}", {"polling": v}, None) for v in RATES]
    cases += [(f"smoothing-{v}", {"smoothing": v}, None) for v in SMOOTHING.values()]
    cases += [(f"downshift-{v}", {"downshift": v}, None) for v in DOWNSHIFT.values()]
    cases += [
        (key, {key: not state[key]}, None)
        for key in [
            "motion_sync",
            "angle_snap",
            "max_fps",
            "slam",
            "jitter",
            "led_liftoff",
        ]
    ]
    cases += [
        ("lod", {"lod": 4 if state["lod"] != 4 else 3}, None),
        ("angle", {"angle": 1 if state["angle"] != 1 else 0}, None),
    ]
    for n in range(4):
        setup = {"count": 4, "active": 1}
        base = patch(baseline, setup)
        x = decode(base)["stages"][n]["x"]
        if not 10 <= x <= 29900:
            continue
        cases.append(
            (
                f"cpi-level-{n + 1}",
                {"stages": {str(n): {"x": x + 100, "y": x + 100, "split": False}}},
                setup,
            )
        )
    cases += [
        ("xy-split", {"stages": {"0": {"x": 1600, "y": 1700, "split": True}}}, None)
    ]
    cases += [(f"count-{n}", {"count": n, "active": 1}, None) for n in range(1, 5)]
    cases += [
        (f"active-{n}", {"active": n}, {"count": 4, "active": 1}) for n in range(1, 5)
    ]
    cases += [
        (
            f"filter-{n}",
            {"filters": {str(n): 9 if state["filters"][n] != 9 else 8}},
            None,
        )
        for n in range(5)
    ]
    cases += [
        (f"gx-{n}-{v}", {"filters": {str(n): v}}, None)
        for n in range(2)
        for v in (240, 241)
    ]
    cases += [
        (
            f"mapping-{name}",
            {
                "buttons": {
                    name: "Cycle CPI"
                    if state["buttons"][name] != "Cycle CPI"
                    else "Middle click"
                }
            },
            None,
        )
        for name in ["Right", "Middle", "Forward", "Back", "Wheel up", "Wheel down"]
    ]
    # Keep a conventional primary click throughout the left-slot test.
    cases += [
        (
            "mapping-Left",
            {"buttons": {"Left": "Right click"}},
            {"buttons": {"Middle": "Left click"}},
        )
    ]
    try:
        for name, changes, setup in cases:
            current = mouse.read()
            if current[16:1040] != baseline[16:1040]:
                raise RuntimeError("Unexpected external profile change before " + name)
            if setup:
                current = mouse.apply(current, setup, folder)
            expected = patch(current, changes)
            actual = mouse.apply(current, changes, folder)
            case = {
                "name": name,
                "changes": changes,
                "setup": setup,
                "before_hex": current.hex(),
                "after_hex": actual.hex(),
                "changed_offsets": [
                    i for i in range(16, 1040) if current[i] != actual[i]
                ],
                "expected_full_payload_equal": actual[16:1040] == expected[16:1040],
                "real_change": actual[16:1040] != current[16:1040],
            }
            restored = mouse.restore(actual, baseline, folder)
            case["original_restored"] = restored[16:1040] == baseline[16:1040]
            report["cases"].append(case)
            args.output.write_text(json.dumps(report, indent=2))
            print(
                name,
                "changed",
                case["changed_offsets"],
                "restored",
                case["original_restored"],
                flush=True,
            )
    finally:
        try:
            current = mouse.read()
            if current[16:1040] != baseline[16:1040]:
                mouse.restore(current, baseline, folder)
            report["final_original_equal"] = mouse.read()[16:1040] == baseline[16:1040]
            args.output.write_text(json.dumps(report, indent=2))
        finally:
            transport.close()


if __name__ == "__main__":
    main()
