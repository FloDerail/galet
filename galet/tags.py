"""Finder-style tags.

Tags are stored on the files themselves in the ``user.xdg.tags`` extended
attribute (comma separated), the freedesktop convention also used by KDE
Dolphin. They therefore follow a file when it is moved or renamed.

A small index (``~/.local/share/galet/index.json``) remembers which files carry
which tags so that the sidebar can list "all red files" instantly. The index is
refreshed every time a folder is displayed. On filesystems without extended
attribute support the index is the only storage.
"""

import errno
import json
import os
from pathlib import Path

from gi.repository import GLib, GObject

from .i18n import N_, _

XATTR = "user.xdg.tags"

# Same order and hues as macOS.
PALETTE = [
    (N_("Red"), "#ff3b30"),
    (N_("Orange"), "#ff9500"),
    (N_("Yellow"), "#ffcc00"),
    (N_("Green"), "#34c759"),
    (N_("Blue"), "#007aff"),
    (N_("Purple"), "#af52de"),
    (N_("Gray"), "#8e8e93"),
]

_UNSUPPORTED = {errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM}

# Network folders exposed through GVfs (kDrive/WebDAV, SMB, SFTP...) never
# support extended attributes, and every attempt is a slow network round trip.
GVFS_ROOT = os.path.join(GLib.get_user_runtime_dir(), "gvfs") + os.sep


class TagStore(GObject.Object):
    __gsignals__ = {
        # The list of tag definitions (names / colours) changed.
        "tags-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # The tags of one file changed (argument: local path).
        "file-tags-changed": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self._defs_path = Path(GLib.get_user_config_dir()) / "galet" / "tags.json"
        self._index_path = Path(GLib.get_user_data_dir()) / "galet" / "index.json"
        self._save_id = 0
        self._no_xattr_dirs = set()
        self.tags = self._load_defs()
        self._index = self._load_index()

    # ---------------------------------------------------------------- storage

    @staticmethod
    def _save_json(path, data):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as err:
            print(f"galet: cannot save {path}: {err}")

    def _load_defs(self):
        try:
            data = json.loads(self._defs_path.read_text(encoding="utf-8"))
            tags = [{"name": str(t["name"]), "color": t.get("color"), "visible": t.get("visible", True)}
                    for t in data]
            if tags:
                return tags
        except (OSError, ValueError, KeyError, TypeError):
            pass
        tags = [{"name": _(name), "color": color, "visible": True} for name, color in PALETTE]
        self._save_json(self._defs_path, tags)
        return tags

    def _load_index(self):
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
            return {str(k): [str(t) for t in v] for k, v in data.items()}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def _schedule_save(self):
        if not self._save_id:
            self._save_id = GLib.timeout_add(800, self._flush_index)

    def _flush_index(self):
        self._save_id = 0
        self._save_json(self._index_path, self._index)
        return GLib.SOURCE_REMOVE

    def flush(self):
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._flush_index()

    def _sync_index(self, path, tags):
        if tags:
            if self._index.get(path) != tags:
                self._index[path] = list(tags)
                self._schedule_save()
        elif path in self._index:
            del self._index[path]
            self._schedule_save()

    # ------------------------------------------------------------ definitions

    def color_of(self, name):
        for tag in self.tags:
            if tag["name"] == name:
                return tag["color"]
        return None

    def add_tag(self, name, color=None):
        name = name.strip().replace(",", " ")
        if name and not any(t["name"] == name for t in self.tags):
            self.tags.append({"name": name, "color": color, "visible": True})
            self._save_json(self._defs_path, self.tags)
            self.emit("tags-changed")
        return name

    def _save_defs(self):
        self._save_json(self._defs_path, self.tags)
        self.emit("tags-changed")

    def set_color(self, name, color):
        for tag in self.tags:
            if tag["name"] == name and tag["color"] != color:
                tag["color"] = color
                self._save_defs()

    def set_visible(self, name, visible):
        for tag in self.tags:
            if tag["name"] == name and tag.get("visible", True) != visible:
                tag["visible"] = visible
                self._save_defs()

    def rename_tag(self, old, new):
        """Rename a tag everywhere. Returns False if the name is taken."""
        new = new.strip().replace(",", " ")
        if not new or new == old or any(t["name"] == new for t in self.tags):
            return False
        for path in self.files_with(old):
            try:
                self.write(path, [new if t == old else t for t in self.read(path)])
            except OSError:
                pass
        for tag in self.tags:
            if tag["name"] == old:
                tag["name"] = new
        self._save_defs()
        return True

    def remove_tag(self, name):
        """Delete a tag definition and strip it from every indexed file."""
        for path in self.files_with(name):
            try:
                self.write(path, [t for t in self.read(path) if t != name])
            except OSError:
                pass
        self.tags = [t for t in self.tags if t["name"] != name]
        self._save_json(self._defs_path, self.tags)
        self.emit("tags-changed")

    # ------------------------------------------------------------- file tags

    def supports_xattr(self, path):
        if path.startswith(GVFS_ROOT):
            return False
        return os.path.dirname(path) not in self._no_xattr_dirs

    def _mark_unsupported(self, path):
        self._no_xattr_dirs.add(os.path.dirname(path))

    def read(self, path):
        """Return the list of tag names of a local file."""
        if not self.supports_xattr(path):
            return list(self._index.get(path, []))
        try:
            raw = os.getxattr(path, XATTR)
            tags = [t.strip() for t in raw.decode("utf-8", "replace").split(",") if t.strip()]
        except OSError as err:
            if err.errno in _UNSUPPORTED:
                self._mark_unsupported(path)
                return list(self._index.get(path, []))
            tags = []  # ENODATA (no tags) or ENOENT
        self._sync_index(path, tags)
        return tags

    def write(self, path, tags):
        """Replace the tags of a file. Raises OSError on failure."""
        unique = []
        for tag in tags:
            if tag and tag not in unique:
                unique.append(tag)
        try:
            if not self.supports_xattr(path):
                pass
            elif unique:
                os.setxattr(path, XATTR, ",".join(unique).encode("utf-8"))
            else:
                try:
                    os.removexattr(path, XATTR)
                except OSError as err:
                    if err.errno != errno.ENODATA:
                        raise
        except OSError as err:
            # No xattr support (FAT, some network shares): keep the index only.
            if err.errno not in _UNSUPPORTED:
                raise
            self._mark_unsupported(path)
        self._sync_index(path, unique)
        self.emit("file-tags-changed", path)

    def toggle(self, paths, name):
        """Add ``name`` to every path, or remove it if all of them have it."""
        current = {p: self.read(p) for p in paths}
        remove = all(name in tags for tags in current.values())
        for path, tags in current.items():
            if remove:
                self.write(path, [t for t in tags if t != name])
            elif name not in tags:
                self.write(path, tags + [name])

    def files_with(self, name):
        result = []
        for path, tags in list(self._index.items()):
            if name not in tags:
                continue
            if not self.supports_xattr(path):
                result.append(path)  # index-only (network): don't touch the server
                continue
            if not os.path.lexists(path):
                self._sync_index(path, [])
                continue
            if name in self.read(path):
                result.append(path)
        return result

    def moved(self, old, new):
        """Keep the index in sync after a rename/move done by Galet."""
        prefix = old.rstrip("/") + "/"
        for path in list(self._index):
            if path == old or path.startswith(prefix):
                self._index[new + path[len(old):]] = self._index.pop(path)
                self._schedule_save()
