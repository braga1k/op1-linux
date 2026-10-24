"""GTK integration tests. Enable explicitly with OP1_TEST_GUI=1."""

import os
import itertools
from pathlib import Path
import tempfile
import unittest

IDENTITIES = itertools.count()
ENABLED = os.environ.get("OP1_TEST_GUI") == "1"
if ENABLED:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib
    from op1.gui import App
    from op1.protocol import demo_blob, patch, ProtocolError


@unittest.skipUnless(ENABLED, "run with OP1_TEST_GUI=1 and a GTK display")
class GuiTests(unittest.TestCase):
    def setUp(self):
        self.app = App(demo=True)
        self.app.set_application_id("local.braga1k.OP1Test" + str(next(IDENTITIES)))
        self.app.register(None)
        self.app.activate()
        while GLib.MainContext.default().iteration(False):
            pass

    def tearDown(self):
        self.app.win.destroy()
        while GLib.MainContext.default().iteration(False):
            pass

    def test_edits_and_revert_control_apply_state(self):
        a = self.app
        self.assertFalse(a.dirty)
        self.assertFalse(a.apply_button.get_sensitive())
        a.controls["polling"].set_selected(3)
        self.assertTrue(a.dirty)
        self.assertTrue(a.apply_button.get_sensitive())
        self.assertIn("polling", a.pending_label.get_text())
        a.controls["polling"].set_selected(6)
        self.assertFalse(a.dirty)

    def test_backing_up_does_not_discard_pending_edits(self):
        a = self.app
        a.controls["angle"].set_value(3)
        changed = a.collect()
        a.finish(
            "backup",
            {
                "report_hex": demo_blob().hex(),
                "writable": True,
                "backup": "/tmp/example.json",
            },
        )
        self.assertEqual(a.collect(), changed)
        self.assertTrue(a.dirty)

    def test_unknown_inactive_cpi_bytes_are_not_rewritten(self):
        a = self.app
        b = bytearray(demo_blob())
        b[30] = 1
        b[29] = 0
        b[56:71] = bytes(15)
        a.load(bytes(b))
        self.assertEqual(a.collect(), {})
        a.controls["count"].set_selected(1)
        with self.assertRaises(ProtocolError):
            patch(a.baseline, a.collect())
        x, y, _, _ = a.stages[1]
        x.set_value(800)
        desired = patch(a.baseline, a.collect())
        self.assertEqual(desired[57:61], b"\x20\x03\x20\x03")

    def test_reducing_count_keeps_active_level_valid(self):
        a = self.app
        a.controls["active"].set_selected(3)
        a.controls["count"].set_selected(0)
        result = patch(a.baseline, a.collect())
        self.assertEqual(result[29:31], b"\0\1")

    def test_uncertain_write_disables_another_apply_and_keeps_edits(self):
        a = self.app
        a.controls["angle"].set_value(3)
        a.finish(
            "apply",
            {
                "error": "Unconfirmed write",
                "uncertain": True,
                "code": "write_uncertain",
            },
        )
        self.assertTrue(a.dirty)
        self.assertFalse(a.apply_button.get_sensitive())
        self.assertEqual(a.controls["angle"].get_value_as_int(), 3)
        self.assertTrue(a.read_button.get_sensitive())

    def test_pending_read_requires_explicit_discard(self):
        a = self.app
        a.controls["angle"].set_value(3)
        confirmations = []
        a.confirm = lambda *args: confirmations.append(args)
        a.run_operation("read")
        self.assertEqual(len(confirmations), 1)
        self.assertFalse(a.busy)
        self.assertTrue(a.dirty)

    def test_close_while_busy_and_pending_is_controlled(self):
        a = self.app
        a.busy = True
        self.assertTrue(a.close_requested())
        a.busy = False
        a.controls["angle"].set_value(3)
        dialogs = []
        a.confirm = lambda *args: dialogs.append(args)
        self.assertTrue(a.close_requested())
        self.assertEqual(len(dialogs), 1)

    def test_second_activation_reuses_the_window(self):
        window = self.app.win
        self.app.activate()
        self.assertIs(window, self.app.win)


if __name__ == "__main__":
    unittest.main()
