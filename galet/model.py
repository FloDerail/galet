"""File items, locations and the list models that feed the views."""

import os
import re
import unicodedata

from gi.repository import Gio, GLib, GObject, Gtk

from .i18n import _

ATTRIBUTES = ",".join((
    "standard::name",
    "standard::display-name",
    "standard::icon",
    "standard::symbolic-icon",
    "standard::content-type",
    "standard::size",
    "standard::type",
    "standard::is-hidden",
    "standard::is-backup",
    "standard::target-uri",
    "time::modified",
    "thumbnail::path",
    "trash::orig-path",
    "trash::deletion-date",
))

_DIGITS = re.compile(r"([0-9]+)")


def natural_key(text):
    """Sort key so that "file2" comes before "file10"."""
    parts = _DIGITS.split(text.casefold())
    return [(0, int(p), "") if i % 2 else (1, 0, p) for i, p in enumerate(parts)]


def fold(text):
    """Case- and accent-insensitive form used for searching ("ete" finds "Été")."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def local_path(gfile, info=None):
    path = gfile.get_path()
    if path is None and info is not None:
        uri = info.get_attribute_string("standard::target-uri")
        if uri and uri.startswith("file://"):
            path = Gio.File.new_for_uri(uri).get_path()
    return path


def display_name(gfile):
    if gfile.get_path() == "/":
        return _("Computer")
    try:
        info = gfile.query_info("standard::display-name", Gio.FileQueryInfoFlags.NONE, None)
        return info.get_display_name()
    except GLib.Error:
        return gfile.get_basename() or gfile.get_uri()


class FileItem(GObject.Object):
    __gtype_name__ = "GaletFileItem"
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, gfile, info, tags):
        super().__init__()
        self.gfile = gfile
        self._apply(info, tags)

    def _apply(self, info, tags):
        # Read attributes defensively: virtual locations (trash, recent,
        # network) do not always provide all of them.
        self.info = info
        self.name = (info.get_attribute_string("standard::display-name")
                     or self.gfile.get_basename() or "")
        file_type = Gio.FileType(info.get_attribute_uint32("standard::type"))
        self.is_dir = file_type in (Gio.FileType.DIRECTORY, Gio.FileType.MOUNTABLE)
        self.size = info.get_attribute_uint64("standard::size")
        modified = info.get_modification_date_time() if info.has_attribute("time::modified") else None
        self.mtime = modified.to_unix() if modified else 0
        self.content_type = info.get_attribute_string("standard::content-type") or ""
        self.hidden = (info.get_attribute_boolean("standard::is-hidden")
                       or info.get_attribute_boolean("standard::is-backup"))
        self.icon = info.get_attribute_object("standard::icon")
        self.thumbnail = info.get_attribute_byte_string("thumbnail::path")
        self.tags = list(tags)
        self.path = local_path(self.gfile, info)
        self.sort_key = natural_key(self.name)
        self.search_key = fold(self.name)
        if self.is_dir:
            self.kind = _("Folder")
        elif self.content_type:
            self.kind = Gio.content_type_get_description(self.content_type)
        else:
            self.kind = _("Document")

    def update(self, info, tags):
        self._apply(info, tags)
        self.emit("changed")

    @property
    def target_file(self):
        """The real file behind recent:/// or other virtual entries."""
        uri = self.info.get_attribute_string("standard::target-uri")
        return Gio.File.new_for_uri(uri) if uri else self.gfile


class Location:
    """A folder (``gfile``), a tag view ("all red files") or a search."""

    __slots__ = ("gfile", "tag", "search")

    def __init__(self, gfile=None, tag=None, search=None):
        self.gfile = gfile
        self.tag = tag
        self.search = search

    @classmethod
    def home(cls):
        return cls(Gio.File.new_for_path(GLib.get_home_dir()))

    @property
    def is_tag(self):
        return self.tag is not None

    @property
    def is_search(self):
        return self.search is not None

    @property
    def is_virtual(self):
        """True for tag views and searches (no real folder behind them)."""
        return self.gfile is None

    def __eq__(self, other):
        if not isinstance(other, Location) or self.tag != other.tag or self.search != other.search:
            return False
        if self.gfile is None or other.gfile is None:
            return self.gfile is other.gfile
        return self.gfile.equal(other.gfile)

    def __hash__(self):
        return hash((self.tag, self.search, self.gfile.get_uri() if self.gfile else None))

    @property
    def title(self):
        if self.is_tag:
            return self.tag
        if self.is_search:
            return self.search.title
        return display_name(self.gfile)


START_LOCATIONS = {
    "desktop": GLib.UserDirectory.DIRECTORY_DESKTOP,
    "documents": GLib.UserDirectory.DIRECTORY_DOCUMENTS,
    "downloads": GLib.UserDirectory.DIRECTORY_DOWNLOAD,
}


def start_location(key):
    """Folder shown in new windows ("home", "recent", "desktop", ...)."""
    if key == "recent":
        return Location(Gio.File.new_for_uri("recent:///"))
    if key in START_LOCATIONS:
        path = GLib.get_user_special_dir(START_LOCATIONS[key])
        if path and os.path.isdir(path):
            return Location(Gio.File.new_for_path(path))
    return Location.home()


# ------------------------------------------------------------------- sorting

def _order(a, b):
    if a < b:
        return Gtk.Ordering.SMALLER
    if a > b:
        return Gtk.Ordering.LARGER
    return Gtk.Ordering.EQUAL


def make_sorter(key=None, folders_first=False, tie_break=True):
    def compare(a, b, *_args):
        if folders_first and a.is_dir != b.is_dir:
            return Gtk.Ordering.SMALLER if a.is_dir else Gtk.Ordering.LARGER
        if key is not None:
            result = _order(key(a), key(b))
            if result != Gtk.Ordering.EQUAL or not tie_break:
                return result
        return _order(a.sort_key, b.sort_key)

    return Gtk.CustomSorter.new(compare)


# -------------------------------------------------------------------- models

def _is_cancelled(err):
    return err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED)


class DirectoryModel(GObject.Object):
    """Asynchronously lists a folder and keeps the list up to date."""

    __gsignals__ = {
        "loaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, gfile, tagstore):
        super().__init__()
        self.gfile = gfile
        self.tagstore = tagstore
        self.store = Gio.ListStore(item_type=FileItem)
        self.loading = True
        self._items = {}
        self._deferred = []
        self._dir_path = gfile.get_path()
        self._cancellable = Gio.Cancellable()
        self._tag_handler = tagstore.connect("file-tags-changed", self._on_file_tags_changed)
        self._monitor = None
        try:
            self._monitor = gfile.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            self._monitor.connect("changed", self._on_monitor_changed)
        except GLib.Error:
            pass
        gfile.enumerate_children_async(ATTRIBUTES, Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
                                       self._cancellable, self._on_enumerated)

    def close(self):
        self._cancellable.cancel()
        if self._monitor is not None:
            self._monitor.cancel()
            self._monitor = None
        if self._tag_handler:
            self.tagstore.disconnect(self._tag_handler)
            self._tag_handler = 0

    def _read_tags(self, gfile, info):
        path = local_path(gfile, info)
        return self.tagstore.read(path) if path else []

    def _on_enumerated(self, gfile, result, *_args):
        try:
            enumerator = gfile.enumerate_children_finish(result)
        except GLib.Error as err:
            if not _is_cancelled(err):
                self.loading = False
                self.emit("error", err.message)
            return
        enumerator.next_files_async(64, GLib.PRIORITY_DEFAULT, self._cancellable, self._on_next_files)

    def _on_next_files(self, enumerator, result, *_args):
        try:
            infos = enumerator.next_files_finish(result)
        except GLib.Error as err:
            if not _is_cancelled(err):
                self.loading = False
                self.emit("error", err.message)
            return
        if not infos:
            self.loading = False
            self.emit("loaded")
            for gfile in self._deferred:
                self._refresh(gfile)
            self._deferred = []
            return
        batch = []
        for info in infos:
            child = enumerator.get_child(info)
            item = FileItem(child, info, self._read_tags(child, info))
            self._items[info.get_name()] = item
            batch.append(item)
        # Show files as they arrive: important on slow network folders.
        self.store.splice(self.store.get_n_items(), 0, batch)
        enumerator.next_files_async(64, GLib.PRIORITY_DEFAULT, self._cancellable, self._on_next_files)

    def _on_monitor_changed(self, _monitor, gfile, other, event):
        events = Gio.FileMonitorEvent
        if event in (events.CREATED, events.MOVED_IN, events.CHANGES_DONE_HINT, events.ATTRIBUTE_CHANGED):
            self._refresh(gfile)
        elif event in (events.DELETED, events.MOVED_OUT):
            self._remove(gfile.get_basename())
        elif event == events.RENAMED:
            self._remove(gfile.get_basename())
            if other is not None:
                self._refresh(other)

    def _on_file_tags_changed(self, _store, path):
        if self._dir_path and os.path.dirname(path) == self._dir_path:
            self._refresh(Gio.File.new_for_path(path))

    def _refresh(self, gfile):
        if self.loading:
            self._deferred.append(gfile)
            return
        gfile.query_info_async(ATTRIBUTES, Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT,
                               self._cancellable, self._on_refreshed)

    def _on_refreshed(self, gfile, result, *_args):
        try:
            info = gfile.query_info_finish(result)
        except GLib.Error:
            return
        name = info.get_name()
        tags = self._read_tags(gfile, info)
        item = self._items.get(name)
        if item is not None:
            item.update(info, tags)
        else:
            item = FileItem(gfile, info, tags)
            self._items[name] = item
            self.store.append(item)

    def _remove(self, name):
        item = self._items.pop(name, None)
        if item is None:
            return
        found, position = self.store.find(item)
        if found:
            self.store.remove(position)


class TagModel(GObject.Object):
    """All indexed files carrying a given tag."""

    __gsignals__ = {
        "loaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self, tag, tagstore):
        super().__init__()
        self.tag = tag
        self.tagstore = tagstore
        self.store = Gio.ListStore(item_type=FileItem)
        self._items = {}
        self._handler = tagstore.connect("file-tags-changed", self._schedule)
        self._source = GLib.idle_add(self._load)

    def close(self):
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0
        if self._handler:
            self.tagstore.disconnect(self._handler)
            self._handler = 0

    def _schedule(self, *_args):
        if not self._source:
            self._source = GLib.timeout_add(150, self._load)

    def _load(self):
        self._source = 0
        paths = self.tagstore.files_with(self.tag)
        for path in list(self._items):
            if path not in paths:
                found, position = self.store.find(self._items.pop(path))
                if found:
                    self.store.remove(position)
        for path in paths:
            gfile = Gio.File.new_for_path(path)
            try:
                info = gfile.query_info(ATTRIBUTES, Gio.FileQueryInfoFlags.NONE, None)
            except GLib.Error:
                continue
            tags = self.tagstore.read(path)
            if path in self._items:
                self._items[path].update(info, tags)
            else:
                self._items[path] = item = FileItem(gfile, info, tags)
                self.store.append(item)
        self.emit("loaded")
        return GLib.SOURCE_REMOVE
