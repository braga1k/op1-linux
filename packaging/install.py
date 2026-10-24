#!/usr/bin/env python3
"""Small user/system-prefix installer; no downloads or privilege escalation."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

ROOT = Path(__file__).resolve().parent.parent
APP_ID = "local.braga1k.OP1Linux"


def main():
    parser = argparse.ArgumentParser(
        description="Install or remove OP1 Linux in a chosen prefix"
    )
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    prefix = args.prefix.expanduser().absolute()
    if any(c in str(prefix) for c in "\n\r%"):
        parser.error("The prefix cannot contain line breaks or %.")
    target = prefix / "lib/op1-linux"
    launcher = prefix / "bin/op1-linux"
    desktop = prefix / f"share/applications/{APP_ID}.desktop"
    marker = target / ".op1-linux-install"
    if target.is_symlink():
        parser.error("Refusing a symlink at the installation directory.")
    if target.exists() and not marker.is_file():
        parser.error("The installation directory is not owned by OP1 Linux.")
    if args.uninstall:
        if not marker.is_file():
            parser.error("No OP1 Linux installation was found in this prefix.")
        for path in [launcher, desktop]:
            if path.is_symlink():
                parser.error("Refusing a symlink at an installed file.")
            if path.exists() and "OP1 Linux" not in path.read_text():
                parser.error(
                    "An installed file was replaced; leaving it untouched: " + str(path)
                )
        shutil.rmtree(target)
        for path in [launcher, desktop]:
            path.unlink(missing_ok=True)
        print(
            "OP1 Linux removed. Profiles and backups in your state directory were kept."
        )
        return
    # Runtime checks intentionally use the system Python/GTK, not build tooling.
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 8):
            raise RuntimeError("GTK 4.8 or newer is required")
    except (ImportError, ValueError, RuntimeError) as error:
        parser.error("Install Python 3, PyGObject and GTK >=4.8 first. " + str(error))
    for path in [launcher, desktop]:
        if path.is_symlink():
            parser.error("Refusing a symlink at an installation file.")
        if path.exists() and "OP1 Linux" not in path.read_text():
            parser.error("A different file already exists: " + str(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".op1-linux-", dir=target.parent))
    previous = target.with_name(".op1-linux-previous")
    if previous.exists():
        parser.error(
            "An interrupted upgrade exists at "
            + str(previous)
            + ". Review it before installing."
        )
    try:
        shutil.copytree(
            ROOT / "op1",
            staging / "op1",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        for name in [
            "README.md",
            "LICENSE",
            "NOTICE",
            "CHANGELOG.md",
            "install-access.sh",
        ]:
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, staging / name)
        shutil.copytree(
            ROOT / "packaging",
            staging / "packaging",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        (staging / ".op1-linux-install").write_text(
            json.dumps({"application": APP_ID, "prefix": str(prefix)}) + "\n"
        )
        if target.exists():
            target.rename(previous)
        staging.rename(target)
        launcher.parent.mkdir(parents=True, exist_ok=True)
        # The launcher computes its prefix and works from arbitrary CWDs.
        launcher.write_text(
            '#!/usr/bin/env python3\n# OP1 Linux launcher\nimport sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent.parent/"lib/op1-linux"))\nfrom op1.__main__ import main\nraise SystemExit(main())\n'
        )
        launcher.chmod(0o755)
        desktop.parent.mkdir(parents=True, exist_ok=True)
        command = (
            str(launcher)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("`", "\\`")
            .replace("$", "\\$")
        )
        desktop.write_text(
            '[Desktop Entry]\nType=Application\nName=OP1 Linux\nComment=Configure your Endgame Gear OP1 8k v2\nExec="'
            + command
            + '"\nIcon=input-mouse\nTerminal=false\nCategories=Settings;HardwareSettings;\nStartupWMClass='
            + APP_ID
            + "\n"
        )
        if previous.exists():
            shutil.rmtree(previous)
        print("Installed OP1 Linux: " + str(launcher))
        print("USB access rule: " + str(target / "packaging/70-op1-linux.rules"))
        print("Backups are stored separately in $XDG_STATE_HOME/op1-linux/backups.")
    except BaseException:
        if previous.exists():
            if target.exists():
                shutil.rmtree(target)
            previous.rename(target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    main()
