"""Drag and drop helpers.

Galet drags real file lists (``Gdk.FileList``), so files can be dropped into
other applications (mail attachments, editors, GNOME Files...) and files dragged
from other applications can be dropped into Galet.

Like Finder, a drop *moves* files on the same disk and *copies* them to another
disk. Hold Ctrl to force a copy, Shift to force a move.
"""

import os

from gi.repository import Gdk, GLib, GObject, Gtk

ACTIONS = Gdk.DragAction.COPY | Gdk.DragAction.MOVE
NO_ACTION = Gdk.DragAction(0)


def files_provider(gfiles):
    file_list = Gdk.FileList.new_from_list(gfiles)
    return Gdk.ContentProvider.new_for_value(GObject.Value(Gdk.FileList, file_list))


def _device(path):
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def same_filesystem(source, destination):
    source_path, destination_path = source.get_path(), destination.get_path()
    if source_path and destination_path:
        device = _device(os.path.dirname(source_path) or source_path)
        return device is not None and device == _device(destination_path)
    if source_path or destination_path:
        return False  # local <-> remote
    # Two remote locations: same server?
    source_uri, destination_uri = source.get_uri(), destination.get_uri()
    authority = lambda uri: uri.split("/", 3)[:3]  # noqa: E731  scheme://user@host
    return authority(source_uri) == authority(destination_uri)


def choose_action(state, sources, destination):
    if state & Gdk.ModifierType.CONTROL_MASK:
        return Gdk.DragAction.COPY
    if state & Gdk.ModifierType.SHIFT_MASK:
        return Gdk.DragAction.MOVE
    if sources and all(same_filesystem(s, destination) for s in sources):
        return Gdk.DragAction.MOVE
    return Gdk.DragAction.COPY


def _files_of(value):
    return list(value.get_files()) if value is not None else []


def add_drag_source(widget, get_files, on_begin=None, on_end=None):
    """Make ``widget`` draggable; ``get_files()`` returns the Gio.Files to drag."""
    source = Gtk.DragSource(actions=ACTIONS)
    if on_end is not None:
        source.connect("drag-end", lambda *_a: on_end())

    def prepare(_source, _x, _y):
        files = get_files()
        return files_provider(files) if files else None

    def begin(src, _drag):
        if on_begin is not None:
            on_begin()
        src.set_icon(Gtk.WidgetPaintable.new(widget), widget.get_width() // 2, widget.get_height() // 2)

    source.connect("prepare", prepare)
    source.connect("drag-begin", begin)
    widget.add_controller(source)
    return source


def add_drop_target(widget, get_destination, on_drop, fixed_action=None):
    """Accept dropped files on ``widget``.

    ``get_destination()`` returns the target (usually a Gio.File) or None to
    refuse; ``on_drop(files, destination, action)`` performs the operation.
    """
    target = Gtk.DropTarget.new(Gdk.FileList, ACTIONS)
    target.set_preload(True)

    def pick_action(drop_target):
        destination = get_destination()
        if destination is None:
            return NO_ACTION
        if fixed_action is not None:
            return fixed_action
        files = _files_of(drop_target.get_value())
        return choose_action(drop_target.get_current_event_state(), files, destination)

    def drop(drop_target, value, _x, _y):
        destination = get_destination()
        files = _files_of(value)
        if destination is None or not files:
            return False
        on_drop(files, destination, pick_action(drop_target))
        return True

    target.connect("enter", lambda t, _x, _y: pick_action(t))
    target.connect("motion", lambda t, _x, _y: pick_action(t))
    target.connect("drop", drop)
    widget.add_controller(target)
    widget.add_css_class("galet-drop")
    return target


SPRING_DELAY_MS = 900


def add_spring_load(widget, get_folder, open_folder):
    """Open a folder when something is dragged over it for a moment."""
    motion = Gtk.DropControllerMotion()
    state = {"source": 0}

    def cancel(*_args):
        if state["source"]:
            GLib.source_remove(state["source"])
            state["source"] = 0

    def fire():
        state["source"] = 0
        folder = get_folder()
        if folder is not None:
            open_folder(folder)
        return GLib.SOURCE_REMOVE

    def enter(*_args):
        cancel()
        if get_folder() is not None:
            state["source"] = GLib.timeout_add(SPRING_DELAY_MS, fire)

    motion.connect("enter", enter)
    motion.connect("leave", cancel)
    widget.add_controller(motion)
