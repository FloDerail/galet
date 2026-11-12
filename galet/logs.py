"""Log file for bug reports: ~/.cache/galet/galet.log.

Python errors (including those raised in GTK callbacks) are written there, so a user can attach the file to a bug report.
"""

import logging
import os
import platform
import sys
import traceback
from pathlib import Path

from gi.repository import GLib

LOG_PATH = Path(GLib.get_user_cache_dir()) / "galet" / "galet.log"
MAX_BYTES = 1024 * 1024

log = logging.getLogger("galet")


def _excepthook(kind, value, tb):
    log.error("Uncaught exception:\n%s", "".join(traceback.format_exception(kind, value, tb)).rstrip())


def setup(version):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH.with_suffix(".log.old"))
        handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.addHandler(logging.StreamHandler())
    log.setLevel(logging.INFO)
    sys.excepthook = _excepthook
    log.info("Galet %s started (Python %s, %s)", version, platform.python_version(), platform.platform())
