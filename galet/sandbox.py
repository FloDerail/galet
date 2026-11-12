"""Helpers for running inside a Flatpak sandbox.

Inside Flatpak, programs of the host system (terminal, thumbnailers, pdftotext,
7z) are reached through ``flatpak-spawn --host``.
"""

import os
import shutil
import subprocess

IN_FLATPAK = os.path.exists("/.flatpak-info")


def host_command(args):
    return ["flatpak-spawn", "--host", *args] if IN_FLATPAK else list(args)


def find_program(name):
    """Return the command prefix to run ``name`` (host program when sandboxed), or None."""
    if not IN_FLATPAK:
        path = shutil.which(name)
        return [path] if path else None
    try:
        found = subprocess.run(host_command(["which", name]), capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return host_command([name]) if found.returncode == 0 else None


def data_dirs():
    """System data directories, including the host's when sandboxed."""
    from gi.repository import GLib

    dirs = list(GLib.get_system_data_dirs())
    if IN_FLATPAK:
        dirs.append("/run/host/usr/share")
    return dirs
