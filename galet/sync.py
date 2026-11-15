"""Merge and synchronise folders: only send what is new or modified.

Used by the "Merge" choice of the copy conflict dialog and by the "Synchronise"
window of the dual pane (local ↔ server). Like rsync's default "quick check", a
file is considered modified when its size differs or when the source is more
recent than the destination (with a tolerance: FTP and some servers round times).
The content is not compared: that would mean downloading every remote file.
"""

import fnmatch

from gi.repository import Gio, GLib

ATTRS = "standard::name,standard::type,standard::size,time::modified,standard::is-symlink"
COPY_FLAGS = Gio.FileCopyFlags.OVERWRITE | Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | Gio.FileCopyFlags.ALL_METADATA
TOLERANCE = 2  # seconds
DEFAULT_EXCLUDES = (".git", ".svn", ".hg", "node_modules", "__pycache__", ".DS_Store", "Thumbs.db",
                    "desktop.ini", "*.tmp", "*.swp", "*~", ".~lock.*#", ".directory")

NEW, MODIFIED, NEWER_THERE, EXTRA = "new", "modified", "newer-there", "extra"


class Entry:
    __slots__ = ("path", "kind", "is_dir", "size", "selected")

    def __init__(self, path, kind, is_dir=False, size=0):
        self.path = path  # relative, with "/"
        self.kind = kind
        self.is_dir = is_dir
        self.size = size
        # files more recent at the destination, and deletions, are opt-in
        self.selected = kind in (NEW, MODIFIED)


class Plan:
    def __init__(self, source, destination):
        self.source = source
        self.destination = destination
        self.entries = []
        self.same = 0
        self.errors = []

    def count(self, kind):
        return sum(1 for e in self.entries if e.kind == kind)

    def selected(self):
        return [e for e in self.entries if e.selected]


def _excluded(name, excludes):
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in excludes)


def _children(folder, cancellable):
    result = {}
    enumerator = folder.enumerate_children(ATTRS, Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    try:
        while True:
            info = enumerator.next_file(cancellable)
            if info is None:
                break
            result[info.get_name()] = info
    finally:
        enumerator.close(None)
    return result


def _mtime(info):
    return info.get_attribute_uint64("time::modified") if info.has_attribute("time::modified") else 0


def is_modified(source_info, destination_info):
    """(changed, destination_is_newer)"""
    src_time, dst_time = _mtime(source_info), _mtime(destination_info)
    if source_info.get_size() != destination_info.get_size():
        return True, bool(src_time and dst_time and dst_time > src_time + TOLERANCE)
    if src_time and dst_time and src_time > dst_time + TOLERANCE:
        return True, False
    return False, False


def scan(source, destination, excludes=(), mirror=False, cancellable=None, progress=None, only=None):
    """Compare two folders recursively. ``progress(text, folders_done)`` is called for each folder.

    ``only``: a set of relative file paths (e.g. the files tracked by Git); folders that
    contain none of them are not visited at all — on a server this saves a lot of time.
    """
    plan = Plan(source, destination)
    wanted_dirs = None
    if only is not None:
        wanted_dirs = {""}
        for path in only:
            parts = path.split("/")[:-1]
            for i in range(1, len(parts) + 1):
                wanted_dirs.add("/".join(parts[:i]))
    folders = [0]

    def walk(src, dst, rel, dst_exists):
        if cancellable is not None and cancellable.is_cancelled():
            return
        folders[0] += 1
        if progress:
            progress(rel or src.get_basename(), folders[0])
        try:
            src_children = _children(src, cancellable)
        except GLib.Error as err:
            plan.errors.append(f"{rel or src.get_basename()}: {err.message}")
            return
        dst_children = {}
        if dst_exists:
            try:
                dst_children = _children(dst, cancellable)
            except GLib.Error:
                dst_children = {}
        for name, info in sorted(src_children.items()):
            if _excluded(name, excludes):
                continue
            path = f"{rel}/{name}" if rel else name
            is_dir = info.get_file_type() == Gio.FileType.DIRECTORY
            if only is not None and (path not in wanted_dirs if is_dir else path not in only):
                continue
            other = dst_children.get(name)
            if is_dir:
                exists = other is not None and other.get_file_type() == Gio.FileType.DIRECTORY
                if not exists:
                    plan.entries.append(Entry(path, NEW, True))
                walk(src.get_child(name), dst.get_child(name), path, exists)
            elif other is None or other.get_file_type() == Gio.FileType.DIRECTORY:
                plan.entries.append(Entry(path, NEW, False, info.get_size()))
            else:
                changed, newer_there = is_modified(info, other)
                if not changed:
                    plan.same += 1
                else:
                    plan.entries.append(Entry(path, NEWER_THERE if newer_there else MODIFIED, False,
                                              info.get_size()))
        if mirror:
            for name, info in sorted(dst_children.items()):
                if name not in src_children and not _excluded(name, excludes):
                    path = f"{rel}/{name}" if rel else name
                    plan.entries.append(Entry(path, EXTRA, info.get_file_type() == Gio.FileType.DIRECTORY,
                                              info.get_size()))

    walk(source, destination, "", destination.query_exists(cancellable))
    return plan


def _delete_tree(gfile, cancellable):
    info = gfile.query_info("standard::type", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    if info.get_file_type() == Gio.FileType.DIRECTORY:
        for name in _children(gfile, cancellable):
            _delete_tree(gfile.get_child(name), cancellable)
    gfile.delete(cancellable)


def apply(plan, entries, cancellable=None, progress=None):
    """Copy/create/delete ``entries`` of ``plan``. Returns (done, errors).

    ``progress(index, total, path, fraction_of_file)`` is called during the transfer.
    Deleted items go to the trash when the destination supports it.
    """
    done, errors = 0, []
    total = len(entries)
    try:
        plan.destination.make_directory_with_parents(cancellable)
    except GLib.Error:
        pass  # already there
    for index, entry in enumerate(entries):
        if cancellable is not None and cancellable.is_cancelled():
            break
        src = plan.source.resolve_relative_path(entry.path)
        dst = plan.destination.resolve_relative_path(entry.path)
        if progress:
            progress(index, total, entry.path, 0.0)
        try:
            if entry.kind == EXTRA:
                try:
                    dst.trash(cancellable)
                except GLib.Error as err:
                    if err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                        raise
                    _delete_tree(dst, cancellable)
            elif entry.is_dir:
                try:
                    dst.make_directory_with_parents(cancellable)
                except GLib.Error as err:
                    if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.EXISTS):
                        raise
            else:
                parent = dst.get_parent()
                if parent is not None and not parent.query_exists(cancellable):
                    parent.make_directory_with_parents(cancellable)

                def on_progress(current, size, *_args, index=index, path=entry.path):
                    if progress:
                        progress(index, total, path, current / size if size else 1.0)

                src.copy(dst, COPY_FLAGS, cancellable, on_progress, None)
            done += 1
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                break
            errors.append(f"{entry.path}: {err.message}")
    return done, errors


def human_size(size):
    return GLib.format_size(size)
