"""Thumbnail generation using the system thumbnailers.

Galet reads ``/usr/share/thumbnailers/*.thumbnailer`` (the same programs GNOME
Files uses: images, videos, PDF, fonts, e-books...) and stores results in the
shared freedesktop cache (``~/.cache/thumbnails/large``), so thumbnails made by
Galet are reused by GNOME Files and vice versa.
"""

import configparser
import hashlib
import os
import queue
import shlex
import subprocess
import tempfile
import threading
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

SIZE = 256
CACHE = Path(GLib.get_user_cache_dir()) / "thumbnails" / "large"
FAIL_DIR = Path(GLib.get_user_cache_dir()) / "thumbnails" / "fail" / "galet"
MAX_FILE_SIZE = 500 * 1024 * 1024
WORKERS = 2
GVFS_ROOT = os.path.join(GLib.get_user_runtime_dir(), "gvfs") + os.sep


def _load_thumbnailers():
    table = {}
    dirs = [Path(d) / "thumbnailers" for d in GLib.get_system_data_dirs()]
    dirs.insert(0, Path(GLib.get_user_data_dir()) / "thumbnailers")
    for directory in dirs:
        for path in sorted(directory.glob("*.thumbnailer")):
            parser = configparser.ConfigParser(interpolation=None)
            try:
                parser.read(path, encoding="utf-8")
                section = parser["Thumbnailer Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            try_exec = section.get("TryExec")
            if try_exec and not GLib.find_program_in_path(try_exec):
                continue
            command = section.get("Exec")
            if not command:
                continue
            for mime in section.get("MimeType", "").split(";"):
                if mime and mime not in table:
                    table[mime] = command
    return table


class Thumbnailer:
    """Background thumbnail queue. ``request(item)`` is cheap and idempotent."""

    def __init__(self):
        self._commands = None
        self._queue = queue.Queue()
        self._pending = set()
        self._started = False

    def _command_for(self, content_type):
        if self._commands is None:
            self._commands = _load_thumbnailers()
        return self._commands.get(content_type)

    def can_thumbnail(self, item):
        if item.thumbnail or item.is_dir or not item.path or item.path.startswith(GVFS_ROOT):
            return False
        if item.size > MAX_FILE_SIZE:
            return False
        return self._command_for(item.content_type) is not None

    def request(self, item):
        if not self.can_thumbnail(item):
            return
        uri = item.gfile.get_uri()
        if uri in self._pending or (FAIL_DIR / _cache_name(uri)).exists():
            return
        self._pending.add(uri)
        if not self._started:
            self._started = True
            for _i in range(WORKERS):
                threading.Thread(target=self._worker, daemon=True).start()
        self._queue.put((item, uri, item.path, item.content_type, item.mtime))

    def _worker(self):
        while True:
            item, uri, path, content_type, mtime = self._queue.get()
            result = None
            try:
                result = self._generate(uri, path, content_type, mtime)
            except Exception as err:  # noqa: BLE001  thumbnailers are external programs
                print(f"galet: thumbnail failed for {path}: {err}")
            GLib.idle_add(self._done, item, uri, result)

    def _done(self, item, uri, result):
        self._pending.discard(uri)
        if result and item.gfile.get_uri() == uri:
            item.thumbnail = result
            item.emit("changed")
        return GLib.SOURCE_REMOVE

    def _generate(self, uri, path, content_type, mtime):
        command = self._command_for(content_type)
        target = CACHE / _cache_name(uri)
        if target.exists():
            return str(target)
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="galet-thumb-") as tmp:
            output = os.path.join(tmp, "thumb.png")
            args = []
            for part in shlex.split(command):
                part = (part.replace("%s", str(SIZE)).replace("%u", uri)
                        .replace("%i", path).replace("%o", output))
                args.append(part)
            completed = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=30, check=False)
            if completed.returncode != 0 or not os.path.exists(output):
                FAIL_DIR.mkdir(parents=True, exist_ok=True)
                (FAIL_DIR / _cache_name(uri)).touch()
                return None
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(output)
            if max(pixbuf.get_width(), pixbuf.get_height()) > SIZE:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(output, SIZE, SIZE, True)
            temp_target = str(target) + f".{os.getpid()}.tmp"
            pixbuf.savev(temp_target, "png", ["tEXt::Thumb::URI", "tEXt::Thumb::MTime"], [uri, str(int(mtime))])
            os.replace(temp_target, target)
        return str(target)


def _cache_name(uri):
    return hashlib.md5(uri.encode("utf-8")).hexdigest() + ".png"


THUMBNAILER = Thumbnailer()


def thumbnail_for(gfile):
    """Existing valid thumbnail path for a file, if any (used after renames)."""
    try:
        info = gfile.query_info("thumbnail::path", Gio.FileQueryInfoFlags.NONE, None)
        return info.get_attribute_byte_string("thumbnail::path")
    except GLib.Error:
        return None
