"""Spotlight-like search: name search in all sub-folders, kind and date filters,
and smart folders (saved searches shown in the sidebar)."""

import os
import threading
import time

from gi.repository import Gio, GLib, GObject

from .i18n import N_, _
from .model import ATTRIBUTES, FileItem, fold

KINDS = (("any", N_("Any Kind")), ("folder", N_("Folders")), ("document", N_("Documents")),
         ("image", N_("Images")), ("pdf", N_("PDF")), ("audio", N_("Music")), ("video", N_("Videos")),
         ("archive", N_("Archives")))
DATES = (("any", N_("Any Date")), ("today", N_("Today")), ("week", N_("Previous 7 Days")),
         ("month", N_("Previous 30 Days")), ("year", N_("This Year")))
DOCUMENT_HINTS = ("text/", "pdf", "opendocument", "msword", "officedocument", "ms-excel", "ms-powerpoint",
                  "rtf", "epub", "markdown")
ARCHIVE_EXTENSIONS = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".zst")
MAX_RESULTS = 3000
SKIPPED_ROOT_DIRS = {"/proc", "/sys", "/dev", "/run", "/snap", "/tmp/.X11-unix"}


def kind_matches(kind, content_type, is_dir, name=""):
    if kind == "any":
        return True
    if kind == "folder":
        return is_dir
    if is_dir:
        return False
    if kind == "document":
        return any(hint in content_type for hint in DOCUMENT_HINTS)
    if kind == "image":
        return content_type.startswith("image/")
    if kind == "pdf":
        return content_type == "application/pdf"
    if kind == "audio":
        return content_type.startswith("audio/")
    if kind == "video":
        return content_type.startswith("video/")
    if kind == "archive":
        return name.lower().endswith(ARCHIVE_EXTENSIONS)
    return True


def date_matches(date, mtime, now=None):
    if date == "any":
        return True
    now = now or time.time()
    local = time.localtime(now)
    midnight = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))
    limits = {
        "today": midnight,
        "week": midnight - 6 * 86400,
        "month": midnight - 29 * 86400,
        "year": time.mktime((local.tm_year, 1, 1, 0, 0, 0, 0, 0, -1)),
    }
    return mtime >= limits.get(date, 0)


class SearchQuery:
    """What to look for. ``root`` is a local folder path ("" = home folder)."""

    __slots__ = ("text", "root", "kind", "date")

    def __init__(self, text="", root="", kind="any", date="any"):
        self.text = text.strip()
        self.root = root or GLib.get_home_dir()
        self.kind = kind
        self.date = date

    def to_dict(self):
        return {"text": self.text, "root": self.root, "kind": self.kind, "date": self.date}

    @classmethod
    def from_dict(cls, data):
        return cls(data.get("text", ""), data.get("root", ""), data.get("kind", "any"), data.get("date", "any"))

    def __eq__(self, other):
        return isinstance(other, SearchQuery) and self.to_dict() == other.to_dict()

    def __hash__(self):
        return hash(tuple(self.to_dict().values()))

    @property
    def is_empty(self):
        return not self.text and self.kind == "any" and self.date == "any"

    @property
    def title(self):
        where = os.path.basename(self.root.rstrip("/")) or "/"
        if self.text:
            return _("“{text}” in {folder}").format(text=self.text, folder=where)
        return _("Search in {folder}").format(folder=where)


class SearchModel(GObject.Object):
    """Results of a SearchQuery, found by a background thread."""

    __gsignals__ = {
        "loaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, query, tagstore, show_hidden=False):
        super().__init__()
        self.query = query
        self.tagstore = tagstore
        self.show_hidden = show_hidden
        self.store = Gio.ListStore(item_type=FileItem)
        self.truncated = False
        self._cancelled = threading.Event()
        threading.Thread(target=self._walk, daemon=True).start()

    def close(self):
        self._cancelled.set()

    def _walk(self):
        query = self.query
        needle = fold(query.text)
        now = time.time()
        pending, found = [], 0
        stack = [query.root]
        while stack and not self._cancelled.is_set():
            directory = stack.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name.startswith(".") and not self.show_hidden:
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir and entry.path not in SKIPPED_ROOT_DIRS and not os.path.ismount(entry.path):
                    stack.append(entry.path)
                if needle and needle not in fold(name):
                    continue
                if query.kind != "any":
                    content_type = "inode/directory" if is_dir else Gio.content_type_guess(name, None)[0]
                    if not kind_matches(query.kind, content_type, is_dir, name):
                        continue
                if query.date != "any":
                    try:
                        if not date_matches(query.date, entry.stat(follow_symlinks=False).st_mtime, now):
                            continue
                    except OSError:
                        continue
                pending.append(entry.path)
                found += 1
                if len(pending) >= 50:
                    GLib.idle_add(self._add, pending)
                    pending = []
                if found >= MAX_RESULTS:
                    self.truncated = True
                    stack = []
                    break
        if pending:
            GLib.idle_add(self._add, pending)
        GLib.idle_add(self._finish)

    def _add(self, paths):
        if self._cancelled.is_set():
            return GLib.SOURCE_REMOVE
        items = []
        for path in paths:
            gfile = Gio.File.new_for_path(path)
            try:
                info = gfile.query_info(ATTRIBUTES, Gio.FileQueryInfoFlags.NONE, None)
            except GLib.Error:
                continue
            items.append(FileItem(gfile, info, self.tagstore.read(path)))
        self.store.splice(self.store.get_n_items(), 0, items)
        return GLib.SOURCE_REMOVE

    def _finish(self):
        if not self._cancelled.is_set():
            self.emit("loaded")
        return GLib.SOURCE_REMOVE


# ------------------------------------------------------------ smart folders

def smart_folders(settings):
    result = []
    for entry in settings.get("smart_folders", []):
        if isinstance(entry, dict) and isinstance(entry.get("query"), dict):
            result.append((str(entry.get("name") or _("Smart Folder")), SearchQuery.from_dict(entry["query"])))
    return result


def save_smart_folder(settings, name, query):
    folders = [e for e in settings.get("smart_folders", []) if isinstance(e, dict) and e.get("name") != name]
    folders.append({"name": name, "query": query.to_dict()})
    settings.set("smart_folders", folders)


def remove_smart_folder(settings, name):
    settings.set("smart_folders", [e for e in settings.get("smart_folders", [])
                                   if isinstance(e, dict) and e.get("name") != name])
