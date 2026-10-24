"""Interface GTK 4. O protocolo corre num subprocesso com tempo limite."""

import json
from pathlib import Path
import subprocess
import sys
import threading
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Gio, Pango
from . import __version__
from .backups import default_directory, load_backup
from .protocol import (
    restore_profile,
    ACTIONS,
    ACTION_SLOTS,
    RATES,
    SMOOTHING,
    DOWNSHIFT,
    decode,
    demo_blob,
    patch,
)

CSS = b"""
window { background: #202124; color: #e8eaed; font-family: sans-serif; font-size: 13px; }
frame { border-color: #51565d; }
headerbar { background: #252629; color: #e8eaed; min-height: 32px; }
.subtitle { color: #aeb4bc; }
.card { background: #252629; border: 1px solid #51565d; border-radius: 0; padding: 12px; }
.section { font-weight: 700; margin-top: 6px; }
button, dropdown button, spinbutton { border-radius: 2px; }
button.suggested-action { background: #3c4046; color: #fff; font-weight: 700; border: 1px solid #8a919b; }
.status { padding: 6px 0; }
.error { color: #ffb4ab; }
.demo { color: #d2d7df; font-weight: 700; }
"""


class App(Gtk.Application):
    def __init__(self, demo=False, smoke=False):
        super().__init__(
            application_id="local.braga1k.OP1Linux",
            flags=Gio.ApplicationFlags.NON_UNIQUE
            if demo or smoke
            else Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.demo, self.smoke = demo, smoke
        self.baseline = None
        self.busy = False
        self.loading = False
        self.dirty = False
        self.writable = demo
        self.stage_touched = set()
        self.controls = {}
        self.stages = []
        self.mappings = {}
        self.filters = []
        self.responsive_rows = []
        self.cpi_value_rows = []
        self.compact = None

    def do_activate(self):
        if getattr(self, "win", None):
            self.win.present()
            return
        self.win = Gtk.ApplicationWindow(application=self, title="OP1 8k v2 · Linux")
        self.win.set_default_size(820, 700)
        self.win.connect("close-request", self.close_requested)
        provider = Gtk.CssProvider()
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(CSS.decode())
        else:
            provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        head = Gtk.HeaderBar()
        head.set_title_widget(Gtk.Label(label="OP1 Linux"))
        self.win.set_titlebar(head)
        about = Gtk.Button(label="About")
        about.connect("clicked", self.about)
        head.pack_end(about)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        for attr in ["top", "bottom", "start", "end"]:
            getattr(outer, "set_margin_" + attr)(12)
        self.win.set_child(outer)
        info = Gtk.Frame(label="Info")
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for side in ["top", "bottom", "start", "end"]:
            getattr(info_box, "set_margin_" + side)(10)
        self.firmware_label = Gtk.Label(label="Firmware version: —", xalign=0)
        info_box.append(self.firmware_label)
        info_box.append(
            Gtk.Label(
                label="Software version: " + __version__ + " · unofficial Linux build",
                xalign=0,
                wrap=True,
            )
        )
        info.set_child(info_box)
        outer.append(info)
        self.status = Gtk.Label(
            label="Connect your mouse and select Read mouse.",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        self.status.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.add_css_class("status")
        outer.append(self.status)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.NONE)
        self.tab_switch = Gtk.StackSwitcher(stack=self.stack, halign=Gtk.Align.START)
        self.tabs_view = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.AUTOMATIC,
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
        )
        self.tabs_view.set_child(self.tab_switch)
        outer.append(self.tabs_view)
        self.page_names = ["Basic", "Advanced Sensor", "Buttons", "Button Mapping"]
        self.tab_choice = Gtk.DropDown.new_from_strings(self.page_names)
        self.tab_choice.set_visible(False)
        outer.append(self.tab_choice)
        self.tab_choice.connect(
            "notify::selected",
            lambda w, *_: self.stack.set_visible_child_name(
                self.page_names[w.get_selected()]
            ),
        )
        self.stack.connect(
            "notify::visible-child-name",
            lambda w, *_: self.tab_choice.set_selected(
                self.page_names.index(w.get_visible_child_name())
            ),
        )
        scroll = Gtk.ScrolledWindow(
            vexpand=True, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC
        )
        scroll.set_child(self.stack)
        outer.append(scroll)
        scroll.get_hadjustment().connect(
            "notify::page-size", lambda *_: GLib.idle_add(self.layout_tick)
        )
        self.basic_page()
        self.sensor_page()
        self.buttons_page()
        self.mapping_page()
        foot = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            column_spacing=8,
            row_spacing=6,
            min_children_per_line=1,
            max_children_per_line=4,
        )
        self.read_button = Gtk.Button(label="Read mouse")
        self.read_button.connect("clicked", lambda *_: self.run_operation("read"))
        self.backup_button = Gtk.Button(label="Back up")
        self.backup_button.connect("clicked", lambda *_: self.run_operation("backup"))
        self.restore_button = Gtk.Button(label="Restore backup…")
        self.restore_button.connect("clicked", self.choose_backup)
        self.apply_button = Gtk.Button(label="Apply to mouse")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self.apply)
        foot.append(self.read_button)
        foot.append(self.backup_button)
        foot.append(self.restore_button)
        foot.append(self.apply_button)
        outer.append(foot)
        hint = Gtk.Label(
            label="Changes are saved only when you apply them. Your previous profile is backed up before every write.",
            wrap=True,
            xalign=0,
        )
        hint.add_css_class("subtitle")
        outer.append(hint)
        self.pending_label = Gtk.Label(label="No pending changes", xalign=0, wrap=True)
        self.pending_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.pending_label.add_css_class("subtitle")
        outer.append(self.pending_label)
        self.connect_edits()
        self.install_shortcuts()
        self.set_enabled(False)
        if self.demo:
            self.load(demo_blob())
            self.status.set_text("DEMO · Sample profile. No USB communication.")
            self.status.add_css_class("demo")
            self.read_button.set_sensitive(False)
            self.backup_button.set_sensitive(False)
            self.apply_button.set_label("Try changes in demo")
        self.ui_ready = True
        GLib.idle_add(self.layout_tick)
        self.win.present()
        if self.smoke:
            GLib.timeout_add(600, self.smoke_check)
        elif not self.demo:
            GLib.idle_add(self.run_operation, "read")

    def smoke_check(self):
        try:
            for name in ["Basic", "Advanced Sensor", "Buttons", "Button Mapping"]:
                self.stack.set_visible_child_name(name)
            assert len(self.stages) == 4 and len(self.mappings) == 7
            assert self.collect() == {}
            self.controls["polling"].set_selected(3)
            assert self.collect()["polling"] == 1000
            print("GTK smoke OK", flush=True)
        except Exception as error:
            self.smoke_failed = True
            print("GTK smoke FAILED:", error, flush=True)
        finally:
            self.quit()
        return False

    def page(self, name):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.add_css_class("card")
        self.stack.add_titled(box, name, name)
        return box

    def label(self, parent, text):
        w = Gtk.Label(label=text, xalign=0)
        w.add_css_class("section")
        parent.append(w)

    def row(self, parent, text, widget):
        row = Gtk.Box(spacing=8)
        label = Gtk.Label(label=text, xalign=0, hexpand=True, wrap=True)
        widget.set_halign(Gtk.Align.END)
        label.set_mnemonic_widget(widget)
        row.append(label)
        row.append(widget)
        parent.append(row)
        self.responsive_rows.append((row, widget))

    def dropdown(self, labels):
        return Gtk.DropDown.new_from_strings(list(labels))

    def choice(self, parent, key, label, options):
        w = self.dropdown(options.keys())
        w.values = list(options.values())
        self.controls[key] = w
        self.row(parent, label, w)

    def number(self, low, high, step=1):
        return Gtk.SpinButton.new_with_range(low, high, step)

    def boolean(self, parent, key, label):
        w = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.controls[key] = w
        self.row(parent, label, w)

    def basic_page(self):
        box = self.page("Basic")
        self.label(box, "Basic settings")
        self.choice(
            box,
            "polling",
            "Polling rate",
            {f"{n:,} Hz".replace(",", " "): n for n in RATES},
        )
        self.choice(
            box,
            "lod",
            "Lift-off distance",
            {f"{(7 + n) / 10:.1f} mm": n for n in range(11)},
        )
        self.boolean(box, "angle_snap", "Angle Snapping")
        self.boolean(box, "led_liftoff", "Disable LED on Lift-Off")
        self.label(box, "CPI settings")
        self.choice(
            box, "count", "Enabled CPI levels", {str(n): n for n in range(1, 5)}
        )
        self.choice(
            box, "active", "Active CPI level", {f"CPI {n}": n for n in range(1, 5)}
        )
        self.controls["count"].connect("notify::selected", self.stage_visibility)
        for n in range(4):
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            heading = Gtk.Box(spacing=8)
            heading.append(Gtk.Label(label=f"CPI {n + 1}", hexpand=True, xalign=0))
            x = self.number(0, 30000, 10)
            y = self.number(0, 30000, 10)
            x.set_width_chars(5)
            y.set_width_chars(5)
            x.set_tooltip_text("Horizontal CPI, from 10 to 30000")
            y.set_tooltip_text("Vertical CPI, from 10 to 30000")
            split = Gtk.CheckButton(label="Separate X/Y")
            split.connect("toggled", lambda w, y=y: y.set_sensitive(w.get_active()))
            heading.append(split)
            row.append(heading)
            values = Gtk.Box(spacing=12)
            for axis, control in [("X", x), ("Y", y)]:
                pair = Gtk.Box(spacing=8)
                pair.append(Gtk.Label(label=axis, xalign=0, hexpand=True))
                pair.append(control)
                values.append(pair)
            row.append(values)
            self.cpi_value_rows.append(values)
            box.append(row)
            self.stages.append((x, y, split, row))
        note = Gtk.Label(
            label="10–10,000 CPI: increments of 10. Above 10,000: increments of 50. Values are rounded when applied.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("subtitle")
        box.append(note)

    def sensor_page(self):
        box = self.page("Advanced Sensor")
        self.label(box, "Sensor settings")
        self.boolean(box, "motion_sync", "Motion Sync")
        self.boolean(box, "jitter", "Motion jitter filter")
        self.boolean(box, "max_fps", "Force maximum sensor FPS")
        angle = self.number(-127, 127)
        self.controls["angle"] = angle
        self.row(box, "Sensor angle tuning", angle)
        self.label(box, "Firmware 1.07 tuning")
        self.choice(box, "smoothing", "Smoothing", SMOOTHING)
        self.choice(box, "downshift", "CPI Downshift", DOWNSHIFT)

    def buttons_page(self):
        box = self.page("Buttons")
        self.boolean(box, "slam", "Slamclick filter")
        self.label(box, "Multiclick & GX modes")
        for n, name in enumerate(list(ACTION_SLOTS)[:5]):
            opts = {f"Multiclick: {i}": i for i in range(26)}
            if n < 2:
                opts.update({"GX Safe": 240, "GX Speed": 241})
            w = self.dropdown(opts)
            w.values = list(opts.values())
            self.filters.append(w)
            self.row(box, name, w)
        note = Gtk.Label(
            label="Existing keyboard bindings and custom actions are kept unchanged. Keep Left click assigned to a physical button.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("subtitle")
        box.append(note)

    def mapping_page(self):
        box = self.page("Button Mapping")
        self.label(box, "Button actions")
        for name in ACTION_SLOTS:
            w = self.dropdown(["Custom (keep unchanged)", *ACTIONS])
            self.mappings[name] = w
            self.row(box, name, w)
        note = Gtk.Label(
            label="Existing keyboard bindings and custom actions are kept unchanged. Keep Left click assigned to a physical button.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("subtitle")
        box.append(note)

    def layout_tick(self, *_):
        compact = self.win.get_width() < 620
        if compact != self.compact:
            self.compact = compact
            self.tabs_view.set_visible(not compact)
            self.tab_choice.set_visible(compact)
            for row, widget in self.responsive_rows:
                row.set_orientation(
                    Gtk.Orientation.VERTICAL if compact else Gtk.Orientation.HORIZONTAL
                )
                widget.set_halign(Gtk.Align.START if compact else Gtk.Align.END)
            for row in self.cpi_value_rows:
                row.set_orientation(
                    Gtk.Orientation.VERTICAL if compact else Gtk.Orientation.HORIZONTAL
                )
        self.status.select_region(0, 0)
        return False

    def stage_visibility(self, *_):
        n = self.controls["count"].get_selected() + 1
        active = self.controls["active"]
        previous = active.get_selected()
        if len(active.values) != n:
            active.values = list(range(1, n + 1))
            active.set_model(Gtk.StringList.new([f"CPI {i}" for i in active.values]))
            active.set_selected(min(previous, n - 1))
        for i, (_, _, _, row) in enumerate(self.stages):
            row.set_sensitive(i < n)

    def set_enabled(self, enabled):
        self.stack.set_sensitive(enabled)
        self.backup_button.set_sensitive(enabled and not self.demo)
        self.restore_button.set_sensitive(enabled and self.writable and not self.demo)
        self.apply_button.set_sensitive(enabled and self.writable and self.dirty)
        self.controls["polling"].set_sensitive(
            enabled and not (self.baseline and decode(self.baseline)["glass"])
        )
        self.controls["lod"].set_sensitive(
            enabled and not (self.baseline and decode(self.baseline)["glass"])
        )

    def load(self, blob):
        self.loading = True
        self.baseline = blob
        state = decode(blob)
        for key, w in self.controls.items():
            v = state[key]
            if isinstance(w, Gtk.Switch):
                w.set_active(v)
            elif isinstance(w, Gtk.SpinButton):
                w.set_value(v)
            else:
                w.set_selected(
                    w.values.index(v) if v in w.values else Gtk.INVALID_LIST_POSITION
                )
        for n, (x, y, split, _) in enumerate(self.stages):
            stage = state["stages"][n]
            x.set_value(stage["x"])
            y.set_value(stage["y"])
            split.set_active(stage["split"])
            y.set_sensitive(stage["split"])
        labels = ["Custom (keep unchanged)", *ACTIONS]
        for name, w in self.mappings.items():
            w.set_selected(labels.index(state["buttons"][name]))
        for value, w in zip(state["filters"], self.filters):
            w.set_selected(
                w.values.index(value)
                if value in w.values
                else Gtk.INVALID_LIST_POSITION
            )
        self.stage_visibility()
        self.loading = False
        self.stage_touched.clear()
        self.dirty = False
        self.pending_label.set_text("No pending changes")
        self.set_enabled(True)

    def collect(self):
        old = decode(self.baseline)
        changes = {}
        for key, w in self.controls.items():
            if isinstance(w, Gtk.Switch):
                v = w.get_active()
            elif isinstance(w, Gtk.SpinButton):
                v = w.get_value_as_int()
            else:
                i = w.get_selected()
                if i == Gtk.INVALID_LIST_POSITION:
                    continue
                v = w.values[i]
            if v != old[key]:
                changes[key] = v
        stages = {}
        for n, (x, y, split, _) in enumerate(self.stages):
            if n not in self.stage_touched:
                continue
            # Inactive slots are preserved; enable a slot before editing it.
            if n >= changes.get("count", old["count"]):
                continue
            v = {
                "x": x.get_value_as_int(),
                "y": y.get_value_as_int(),
                "split": split.get_active(),
            }
            if not v["split"]:
                v["y"] = v["x"]
            if v != old["stages"][n]:
                stages[str(n)] = v
        if stages:
            changes["stages"] = stages
        buttons = {}
        for name, w in self.mappings.items():
            action = w.get_selected_item().get_string()
            if action != "Custom (keep unchanged)" and action != old["buttons"][name]:
                buttons[name] = action
        if buttons:
            changes["buttons"] = buttons
        filters = {
            str(n): w.values[w.get_selected()]
            for n, w in enumerate(self.filters)
            if w.get_selected() != Gtk.INVALID_LIST_POSITION
            and w.values[w.get_selected()] != old["filters"][n]
        }
        if filters:
            changes["filters"] = filters
        return changes

    def apply(self, *_):
        try:
            changes = self.collect()
            blob = patch(self.baseline, changes)
            if blob == self.baseline:
                self.status.set_text("There are no changes to apply.")
                return
            if self.demo:
                self.load(blob)
                self.status.set_text(
                    "DEMO · Changes validated in the sample profile only."
                )
                return
            self.run_operation(
                "apply", {"baseline": self.baseline.hex(), "changes": changes}
            )
        except Exception as e:
            self.status.set_text(str(e))
            self.status.add_css_class("error")

    def install_shortcuts(self):
        for name, shortcut, button in [
            ("read", "<Control>r", self.read_button),
            ("backup", "<Control>b", self.backup_button),
            ("apply", "<Control>Return", self.apply_button),
        ]:
            action = Gio.SimpleAction.new(name, None)
            action.connect(
                "activate",
                lambda action, param, button=button: button.emit("clicked")
                if button.get_sensitive()
                else None,
            )
            self.add_action(action)
            self.set_accels_for_action("app." + name, [shortcut])
        for index, name in enumerate(self.page_names, 1):
            action = Gio.SimpleAction.new("page" + str(index), None)
            action.connect(
                "activate",
                lambda action, param, name=name: self.stack.set_visible_child_name(
                    name
                ),
            )
            self.add_action(action)
            self.set_accels_for_action(
                "app.page" + str(index), ["<Control>" + str(index)]
            )

    def connect_edits(self):
        for w in self.controls.values():
            signal = (
                "notify::active"
                if isinstance(w, Gtk.Switch)
                else "value-changed"
                if isinstance(w, Gtk.SpinButton)
                else "notify::selected"
            )
            w.connect(signal, self.edited)
        for n, (x, y, split, _) in enumerate(self.stages):
            for w, signal in [
                (x, "value-changed"),
                (y, "value-changed"),
                (split, "toggled"),
            ]:
                w.connect(signal, self.stage_edited, n)
        for w in [*self.mappings.values(), *self.filters]:
            w.connect("notify::selected", self.edited)

    def stage_edited(self, w, *args):
        if not self.loading:
            self.stage_touched.add(args[-1])
            self.edited()

    def edited(self, *_):
        if self.loading or not self.baseline:
            return
        try:
            changes = self.collect()
            desired = patch(self.baseline, changes)
            self.dirty = desired[16:1040] != self.baseline[16:1040]
            labels = {
                "polling": "polling rate",
                "count": "CPI levels",
                "active": "active level",
                "stages": "CPI values",
                "buttons": "button actions",
                "filters": "button filters",
                "lod": "lift-off",
                "angle": "angle",
                "smoothing": "smoothing",
                "downshift": "CPI Downshift",
            }
            summary = ", ".join(labels.get(k, k.replace("_", " ")) for k in changes)
            self.pending_label.set_text(
                "Pending: " + summary if self.dirty else "No pending changes"
            )
            self.pending_label.remove_css_class("error")
        except Exception as error:
            self.dirty = True
            self.pending_label.set_text(str(error))
            self.pending_label.add_css_class("error")
        self.apply_button.set_sensitive(self.dirty and self.writable and not self.busy)

    def confirm(self, title, detail, action, callback):
        dialog = Gtk.MessageDialog(
            transient_for=self.win,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=title,
            secondary_text=detail,
        )
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(action, Gtk.ResponseType.ACCEPT)
        dialog.set_default_response(Gtk.ResponseType.CANCEL)

        def response(d, result):
            d.destroy()
            if result == Gtk.ResponseType.ACCEPT:
                callback()

        dialog.connect("response", response)
        dialog.present()

    def close_requested(self, *_):
        if self.busy:
            self.status.set_text(
                "Please wait for the operation to finish before closing."
            )
            return True
        if self.dirty:
            self.confirm(
                "Discard pending changes?",
                "These changes have not been saved to the mouse.",
                "Discard and close",
                self.win.destroy,
            )
            return True
        return False

    def choose_backup(self, *_):
        chooser = Gtk.FileChooserNative(
            title="Choose an OP1 backup",
            transient_for=self.win,
            action=Gtk.FileChooserAction.OPEN,
            accept_label="Review backup",
            cancel_label="Cancel",
        )
        file_filter = Gtk.FileFilter()
        file_filter.set_name("OP1 backups (*.json)")
        file_filter.add_pattern("*.json")
        chooser.add_filter(file_filter)
        from gi.repository import Gio

        folder = default_directory()
        if folder.exists():
            chooser.set_current_folder(Gio.File.new_for_path(str(folder)))

        def chosen(dialog, result):
            if result == Gtk.ResponseType.ACCEPT:
                path = dialog.get_file().get_path()
                try:
                    saved, document = load_backup(Path(path))
                    desired = restore_profile(self.baseline, saved)
                    state = decode(desired)
                    warning = (
                        " Legacy backup without a checksum."
                        if document["format"].endswith("v1")
                        else ""
                    )
                    detail = (
                        f"{state['polling']} Hz · {state['count']} level(s) · active CPI level {state['active']}. The current profile will be backed up before writing."
                        + warning
                    )
                    if self.dirty:
                        detail += " Pending edits will be discarded after restoring."
                    self.confirm(
                        "Restore this profile?",
                        detail,
                        "Restore",
                        lambda: self.run_operation(
                            "restore",
                            {"baseline": self.baseline.hex(), "path": path},
                            confirmed=True,
                        ),
                    )
                except Exception as error:
                    self.status.set_text(str(error))
                    self.status.add_css_class("error")
            dialog.destroy()

        chooser.connect("response", chosen)
        chooser.show()

    def run_operation(self, operation, payload=None, confirmed=False):
        if self.busy:
            return
        if operation == "read" and self.dirty and not confirmed:
            self.confirm(
                "Read mouse and discard changes?",
                "The profile saved on the mouse will replace your pending edits.",
                "Read mouse",
                lambda: self.run_operation(operation, payload, True),
            )
            return
        self.busy = True
        self.set_enabled(False)
        self.read_button.set_sensitive(False)
        self.status.remove_css_class("error")
        self.status.set_text(
            {
                "read": "Reading the mouse profile…",
                "apply": "Backing up, applying and verifying…",
                "backup": "Backing up the mouse profile…",
                "restore": "Backing up the current profile and restoring…",
            }[operation]
        )

        def work():
            try:
                process = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "import sys;sys.path.insert(0,sys.argv.pop(1));from op1.__main__ import main;raise SystemExit(main())",
                        str(Path(__file__).resolve().parent.parent),
                        "--worker",
                        operation,
                    ],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                try:
                    result = json.loads(process.stdout)
                except json.JSONDecodeError:
                    result = {
                        "error": "Communication ended without a valid response. Read the mouse again.",
                        "code": "worker_failed",
                        "uncertain": operation in ("apply", "restore"),
                    }
                if process.returncode and "error" not in result:
                    result = {
                        "error": "The operation failed. Read the mouse again.",
                        "code": "worker_failed",
                        "uncertain": operation in ("apply", "restore"),
                    }
            except subprocess.TimeoutExpired:
                uncertain = operation in ("apply", "restore")
                result = {
                    "error": "Communication timed out. "
                    + (
                        "Writing may have occurred; read the mouse again. Backups are in "
                        + str(default_directory())
                        if uncertain
                        else "Reconnect the mouse and try again."
                    ),
                    "code": "timeout",
                    "uncertain": uncertain,
                }
            except Exception as error:
                result = {"error": str(error), "code": "worker_failed"}
            GLib.idle_add(self.finish, operation, result)

        threading.Thread(target=work, daemon=True).start()

    def finish(self, operation, result):
        self.busy = False
        self.read_button.set_sensitive(True)
        if "error" in result:
            self.status.set_text(result["error"])
            self.status.add_css_class("error")
            # Keep edits visible. Uncertain state requires a new read before writing.
            self.set_enabled(
                bool(self.baseline)
                and not result.get("uncertain")
                and result.get("code")
                not in ("disconnected", "device_missing", "permission_denied")
            )
        else:
            self.writable = result.get("writable", False)
            if operation != "backup":
                self.load(bytes.fromhex(result["report_hex"]))
            else:
                self.set_enabled(bool(self.baseline))
            message = {
                "read": "Profile read from the mouse. Firmware "
                + result.get("firmware", "unknown")
                + ".",
                "apply": "Profile applied and fully verified.",
                "backup": "Backup saved: " + result.get("backup", ""),
                "restore": "Profile restored and fully verified.",
            }[operation]
            if not self.writable:
                message += (
                    " Read-only mode: writing is validated only for firmware 1.07."
                )
            self.status.set_text(message)
            self.firmware_label.set_text(
                "Firmware version: " + result.get("firmware", "—")
            )
        return False

    def about(self, *_):
        dlg = Gtk.AboutDialog(
            transient_for=self.win,
            modal=True,
            program_name="OP1 Linux",
            version=__version__,
            comments="Unofficial configurator. Protocol analysis of the 1.07 executable using REA/Ghidra. Additional reference: qsxcv/UnofficialEGGWebConfig. No warranty.",
            website="https://github.com/qsxcv/UnofficialEGGWebConfig",
            license_type=Gtk.License.AGPL_3_0,
            authors=[
                "Linux implementation: Vitor Ferreira / Codex",
                "Protocol reference: qsxcv and contributors",
            ],
        )
        dlg.present()
