"""What the AI saw in your photos, kept on your computer.

``~/.local/share/galet/photo-index.json`` maps a photo's path to the keywords and
caption the AI produced, with the file's modification time so a changed photo
is analysed again. Search uses it to find "beach photos" named IMG_2034.jpg.
"""

import json
import os
import threading
from pathlib import Path

from gi.repository import GLib

from .model import fold

INDEX_PATH = Path(GLib.get_user_data_dir()) / "galet" / "photo-index.json"
PHOTO_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".heic", ".heif")


def is_photo(path):
    return path.lower().endswith(PHOTO_EXTENSIONS)


class PhotoIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = None
        self._folded = {}

    def _load(self):
        if self._entries is not None:
            return
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            self._entries = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        except (OSError, ValueError, AttributeError):
            self._entries = {}
        self._folded = {path: self._fold_entry(entry) for path, entry in self._entries.items()}

    @staticmethod
    def _fold_entry(entry):
        return fold(" ".join([*entry.get("keywords", []), entry.get("caption", "")]))

    def words(self, path):
        """Folded keywords + caption of an analysed photo ("" if unknown)."""
        with self._lock:
            self._load()
            return self._folded.get(path, "")

    def entry(self, path):
        with self._lock:
            self._load()
            return self._entries.get(path)

    def is_current(self, path):
        entry = self.entry(path)
        if entry is None:
            return False
        try:
            return int(os.stat(path).st_mtime) == entry.get("mtime")
        except OSError:
            return False

    def add(self, path, keywords, caption):
        try:
            mtime = int(os.stat(path).st_mtime)
        except OSError:
            return
        entry = {"mtime": mtime, "keywords": [str(k) for k in keywords][:40], "caption": str(caption)[:300]}
        with self._lock:
            self._load()
            self._entries[path] = entry
            self._folded[path] = self._fold_entry(entry)

    def save(self):
        with self._lock:
            if self._entries is None:
                return
            INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = INDEX_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._entries, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, INDEX_PATH)

    def count(self):
        with self._lock:
            self._load()
            return len(self._entries)

    def clear(self):
        with self._lock:
            self._entries, self._folded = {}, {}
        self.save()

    def moved(self, old, new):
        with self._lock:
            self._load()
            prefix = old.rstrip("/") + "/"
            for path in list(self._entries):
                if path == old or path.startswith(prefix):
                    target = new + path[len(old):]
                    self._entries[target] = self._entries.pop(path)
                    self._folded[target] = self._folded.pop(path, "")


PHOTO_INDEX = PhotoIndex()
