"""File operations: open, rename, trash, copy/move with progress, undo."""

import subprocess
import threading

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from .i18n import _, ngettext

GNOME_COPIED_FILES = "x-special/gnome-copied-files"
URI_LIST = "text/uri-list"
_COPY_FLAGS = Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | Gio.FileCopyFlags.ALL_METADATA
TRASH = "trash:///"
MAX_UNDO = 30


def _io_error(err, code):
    return err.matches(Gio.io_error_quark(), code)


# ----------------------------------------------------------------------- undo

def push_undo(window, label, undo):
    """Remember how to revert an operation (Ctrl+Z / the toast's Undo button)."""
    stack = window.app.undo_stack
    stack.append((label, undo))
    del stack[:-MAX_UNDO]
    return True


def undo_last(window):
    stack = window.app.undo_stack
    if not stack:
        window.toast(_("Nothing to undo"))
        return
    label, undo = stack.pop()
    undo(window)
    window.toast(_("Undone: {action}").format(action=label))


# ------------------------------------------------------------------ launching

def launch(window, gfile, always_ask=False):
    launcher = Gtk.FileLauncher.new(gfile)
    launcher.set_always_ask(always_ask)

    def done(source, result, *_args):
        try:
            source.launch_finish(result)
        except GLib.Error as err:
            if not err.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                window.toast(_("Could not open “{name}”: {error}").format(
                    name=gfile.get_basename(), error=err.message))

    launcher.launch(window, None, done)


def quicklook(window, item):
    """Show the file in GNOME Sushi (the space-bar previewer used by Files)."""

    def done(connection, result, *_args):
        try:
            connection.call_finish(result)
        except GLib.Error:
            window.toast(_("Quick Look needs the “gnome-sushi” package."))

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return
    bus.call("org.gnome.NautilusPreviewer", "/org/gnome/NautilusPreviewer",
             "org.gnome.NautilusPreviewer2", "ShowFile",
             GLib.Variant("(ssb)", (item.gfile.get_uri(), "", True)),
             None, Gio.DBusCallFlags.NONE, -1, None, done)


def open_terminal(window, gfile):
    path = gfile.get_path() if gfile else None
    if not path:
        return
    from .sandbox import find_program

    for program in ("ptyxis", "kgx", "gnome-terminal", "xdg-terminal-exec"):
        command = find_program(program)
        if command:
            args = [] if program == "xdg-terminal-exec" else [f"--working-directory={path}"]
            subprocess.Popen([*command, *args], cwd=path, start_new_session=True)
            return
    window.toast(_("No terminal application found."))


# -------------------------------------------------------------------- dialogs

def ask_text(window, heading, initial, confirm, callback, select_stem=False):
    dialog = Adw.AlertDialog(heading=heading)
    entry = Gtk.Entry(text=initial, activates_default=True)
    dialog.set_extra_child(entry)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("ok", confirm)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    def select_name(*_args):
        entry.grab_focus()
        select_stem_region(entry, initial, select_stem)
        return GLib.SOURCE_REMOVE

    def on_response(_dialog, response):
        text = entry.get_text().strip()
        if response == "ok" and text:
            callback(text)

    entry.connect("map", lambda *_a: GLib.idle_add(select_name))
    dialog.connect("response", on_response)
    dialog.present(window)


def select_stem_region(entry, name, select_stem=True):
    end = len(name)
    if select_stem and "." in name[1:]:
        end = len(name.rsplit(".", 1)[0])
    entry.select_region(0, end)


def confirm(window, heading, body, action_label, callback, destructive=True):
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("ok", action_label)
    dialog.set_response_appearance(
        "ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, r: callback() if r == "ok" else None)
    dialog.present(window)


# --------------------------------------------------------------------- rename

def rename_to(window, gfile, new_name, record=True):
    old_name = gfile.get_basename()
    old_path = gfile.get_path()
    if not new_name or new_name == old_name:
        return

    def done(source, result, *_args):
        try:
            new_file = source.set_display_name_finish(result)
        except GLib.Error as err:
            window.toast(_("Could not rename: {error}").format(error=err.message))
            return
        if old_path and new_file.get_path():
            window.tagstore.moved(old_path, new_file.get_path())
        if record:
            push_undo(window, _("Rename"), lambda w: rename_to(w, new_file, old_name, record=False))

    gfile.set_display_name_async(new_name, GLib.PRIORITY_DEFAULT, None, done)


def rename(window, item):
    """Dialog fallback when inline renaming is not possible."""
    ask_text(window, _("Rename"), item.name, _("Rename"), lambda name: rename_to(window, item.gfile, name),
             select_stem=not item.is_dir)


def new_folder(window, directory, on_created=None, name=None):
    """Create "untitled folder" right away (like Finder) and report it."""
    folder = unique_child(directory, name or _("untitled folder"))

    def done(gfile, result, *_args):
        try:
            gfile.make_directory_finish(result)
        except GLib.Error as err:
            window.toast(_("Could not create the folder: {error}").format(error=err.message))
            return
        push_undo(window, _("New Folder"), lambda w: trash_files(w, [gfile], record=False))
        if on_created is not None:
            on_created(gfile)

    folder.make_directory_async(GLib.PRIORITY_DEFAULT, None, done)


def new_folder_with_selection(window, directory, items, on_created=None):
    uris = [i.gfile.get_uri() for i in items]

    def created(folder):
        transfer(window, uris, folder, move=True,
                 on_done=lambda _pairs: on_created(folder) if on_created else None)

    new_folder(window, directory, created, name=_("New Folder With Items"))


def duplicate(window, items):
    by_parent = {}
    for item in items:
        parent = item.gfile.get_parent()
        if parent is not None:
            by_parent.setdefault(parent.get_uri(), (parent, []))[1].append(item.gfile.get_uri())
    for parent, uris in by_parent.values():
        transfer(window, uris, parent, move=False)


# ---------------------------------------------------------------------- trash

def trash(window, items):
    trash_files(window, [item.gfile for item in items])


def trash_files(window, gfiles, record=True):
    gfiles = list(gfiles)
    if not gfiles:
        return
    remaining = [len(gfiles)]
    errors, trashed = [], []

    def done(gfile, result, *_args):
        try:
            gfile.trash_finish(result)
            trashed.append(gfile)
        except GLib.Error as err:
            errors.append(err.message)
        remaining[0] -= 1
        if remaining[0]:
            return
        if errors:
            window.toast(_("Could not move to the trash: {error}").format(error=errors[0]))
        if trashed:
            paths = [f.get_path() for f in trashed if f.get_path()]
            undoable = record and paths and push_undo(window, _("Move to Trash"),
                                                      lambda w: restore_trashed(w, paths))
            count = len(trashed)
            window.toast(ngettext("{n} item moved to the trash", "{n} items moved to the trash",
                                  count).format(n=count), undo=bool(undoable))

    for gfile in gfiles:
        gfile.trash_async(GLib.PRIORITY_DEFAULT, None, done)


def _run(window, title, work, finished):
    """Run ``work(operation, errors)`` in a thread, then ``finished(result, errors)``."""
    from .operations import Operation

    operation = window.start_operation(Operation(title))
    errors = []

    def worker():
        result = None
        try:
            result = work(operation, errors)
        except GLib.Error as err:
            if not _io_error(err, Gio.IOErrorEnum.CANCELLED):
                errors.append(err.message)
        GLib.idle_add(done, result)

    def done(result):
        operation.finish()
        finished(result, errors)
        return GLib.SOURCE_REMOVE

    threading.Thread(target=worker, daemon=True).start()
    return operation


def _restore(window, pairs, title):
    """Move (trash item, original Gio.File) pairs back out of the trash."""

    def work(operation, errors):
        restored = []
        for index, (source, destination) in enumerate(pairs):
            operation.update(detail=destination.get_basename(), fraction=index / len(pairs))
            try:
                if destination.query_exists(None):
                    destination = unique_child(destination.get_parent(), destination.get_basename())
                parent = destination.get_parent()
                if parent is not None and not parent.query_exists(None):
                    parent.make_directory_with_parents(None)
                _move_one(source, destination, operation.cancellable)
                restored.append(destination)
            except GLib.Error as err:
                errors.append(f"{destination.get_basename()}: {err.message}")
        return restored

    def finished(restored, errors):
        if errors:
            window.toast(_("Could not restore: {error}").format(error=errors[0]))
        elif restored:
            count = len(restored)
            window.toast(ngettext("{n} item put back", "{n} items put back", count).format(n=count))

    _run(window, title, work, finished)


def restore_trashed(window, paths):
    """Undo of "Move to Trash": find the most recent trash entries for ``paths``."""
    wanted = set(paths)
    trash_dir = Gio.File.new_for_uri(TRASH)
    latest = {}
    try:
        enumerator = trash_dir.enumerate_children(
            "standard::name,trash::orig-path,trash::deletion-date", Gio.FileQueryInfoFlags.NONE, None)
        while True:
            info = enumerator.next_file(None)
            if info is None:
                break
            original = info.get_attribute_byte_string("trash::orig-path")
            date = info.get_attribute_string("trash::deletion-date") or ""
            if original in wanted and (original not in latest or date > latest[original][0]):
                latest[original] = (date, trash_dir.get_child(info.get_name()))
    except GLib.Error as err:
        window.toast(_("Could not restore: {error}").format(error=err.message))
        return
    pairs = [(entry, Gio.File.new_for_path(original)) for original, (_d, entry) in latest.items()]
    if pairs:
        _restore(window, pairs, _("Putting Back"))


def put_back(window, items):
    pairs = []
    for item in items:
        original = item.info.get_attribute_byte_string("trash::orig-path")
        if original:
            pairs.append((item.gfile, Gio.File.new_for_path(original)))
    if pairs:
        _restore(window, pairs, _("Putting Back"))


def empty_trash(window):
    def run():
        def work(operation, errors):
            trash_dir = Gio.File.new_for_uri(TRASH)
            enumerator = trash_dir.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NONE, None)
            while not operation.cancellable.is_cancelled():
                info = enumerator.next_file(None)
                if info is None:
                    break
                operation.update(detail=info.get_name())
                try:
                    trash_dir.get_child(info.get_name()).delete(operation.cancellable)
                except GLib.Error as err:
                    errors.append(err.message)

        _run(window, _("Emptying the Trash"), work,
             lambda _r, errors: window.toast(errors[0]) if errors else None)

    confirm(window, _("Empty the Trash?"), _("All items in the trash will be permanently deleted."),
            _("Empty Trash"), run)


def delete_permanently(window, gfiles):
    gfiles = list(gfiles)
    count = len(gfiles)

    def run():
        def work(operation, errors):
            for index, gfile in enumerate(gfiles):
                operation.update(detail=gfile.get_basename(), fraction=index / count)
                try:
                    _delete_recursive(gfile, operation.cancellable)
                except GLib.Error as err:
                    errors.append(f"{gfile.get_basename()}: {err.message}")

        _run(window, _("Deleting"), work, lambda _r, errors: window.toast(errors[0]) if errors else None)

    confirm(window, ngettext("Permanently delete {n} item?", "Permanently delete {n} items?", count).format(n=count),
            _("This cannot be undone."), _("Delete"), run)


# ------------------------------------------------------------------ clipboard

def _text_provider(text):
    return Gdk.ContentProvider.new_for_value(GObject.Value(GObject.TYPE_STRING, text))


def copy_paths(window, items):
    text = "\n".join(i.path or i.gfile.get_uri() for i in items)
    window.get_clipboard().set_content(_text_provider(text))
    window.toast(_("Path copied"))


def copy_to_clipboard(window, items, cut):
    uris = [i.gfile.get_uri() for i in items]
    window.app.clipboard_files = (cut, uris)
    gnome = ("cut" if cut else "copy") + "\n" + "\n".join(uris)
    text = "\n".join(i.path or i.gfile.get_uri() for i in items)
    provider = Gdk.ContentProvider.new_union([
        Gdk.ContentProvider.new_for_bytes(GNOME_COPIED_FILES, GLib.Bytes.new(gnome.encode())),
        Gdk.ContentProvider.new_for_bytes(URI_LIST, GLib.Bytes.new(("\r\n".join(uris) + "\r\n").encode())),
        _text_provider(text),
    ])
    window.get_clipboard().set_content(provider)


def paste(window, directory):
    clipboard = window.get_clipboard()
    if clipboard.is_local() and window.app.clipboard_files:
        cut, uris = window.app.clipboard_files
        if cut:
            window.app.clipboard_files = None
        transfer(window, uris, directory, move=cut)
        return

    def on_read(source, result, *_args):
        try:
            stream, mime = source.read_finish(result)
        except GLib.Error:
            window.toast(_("Nothing to paste"))
            return
        output = Gio.MemoryOutputStream.new_resizable()

        def on_spliced(out, res, *_a):
            try:
                out.splice_finish(res)
            except GLib.Error:
                return
            data = out.steal_as_bytes().get_data().decode("utf-8", "replace")
            lines = [line.strip() for line in data.splitlines() if line.strip() and not line.startswith("#")]
            cut = False
            if mime == GNOME_COPIED_FILES and lines and lines[0] in ("copy", "cut"):
                cut = lines.pop(0) == "cut"
            if lines:
                transfer(window, lines, directory, move=cut)

        output.splice_async(stream, Gio.OutputStreamSpliceFlags.CLOSE_SOURCE
                            | Gio.OutputStreamSpliceFlags.CLOSE_TARGET,
                            GLib.PRIORITY_DEFAULT, None, on_spliced)

    clipboard.read_async([GNOME_COPIED_FILES, URI_LIST], GLib.PRIORITY_DEFAULT, None, on_read)


# ---------------------------------------------------------- copy / move core

def _split_ext(name):
    if "." in name[1:]:
        stem, ext = name.rsplit(".", 1)
        return stem, "." + ext
    return name, ""


def unique_child(directory, name):
    candidate = directory.get_child(name)
    if not candidate.query_exists(None):
        return candidate
    stem, ext = _split_ext(name)
    number = 1
    while True:
        if number == 1:
            new_name = _("{name} copy{ext}").format(name=stem, ext=ext)
        else:
            new_name = _("{name} copy {n}{ext}").format(name=stem, n=number, ext=ext)
        candidate = directory.get_child(new_name)
        if not candidate.query_exists(None):
            return candidate
        number += 1


def _copy_recursive(source, destination, cancellable=None, progress=None):
    info = source.query_info("standard::type", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    if info.get_file_type() != Gio.FileType.DIRECTORY:
        source.copy(destination, _COPY_FLAGS, cancellable, progress, None)
        return
    destination.make_directory(cancellable)
    enumerator = source.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                           cancellable)
    while True:
        child = enumerator.next_file(cancellable)
        if child is None:
            break
        name = child.get_name()
        _copy_recursive(source.get_child(name), destination.get_child(name), cancellable, progress)
    enumerator.close(None)
    try:
        source.copy_attributes(destination, _COPY_FLAGS, cancellable)
    except GLib.Error:
        pass


def _delete_recursive(gfile, cancellable=None):
    info = gfile.query_info("standard::type", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, cancellable)
    if info.get_file_type() == Gio.FileType.DIRECTORY:
        enumerator = gfile.enumerate_children("standard::name", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                                              cancellable)
        while True:
            child = enumerator.next_file(cancellable)
            if child is None:
                break
            _delete_recursive(gfile.get_child(child.get_name()), cancellable)
        enumerator.close(None)
    gfile.delete(cancellable)


def _move_one(source, destination, cancellable=None, progress=None):
    try:
        source.move(destination, _COPY_FLAGS, cancellable, progress, None)
    except GLib.Error as err:
        if not _io_error(err, Gio.IOErrorEnum.WOULD_RECURSE):
            raise
        _copy_recursive(source, destination, cancellable, progress)
        _delete_recursive(source, cancellable)


def ask_conflict(window, operation, name):
    """Ask from the worker thread what to do with an existing item.

    Returns ("replace" | "keep" | "skip", apply_to_all).
    """
    answered = threading.Event()
    answer = {"response": "skip", "all": False}

    def show():
        dialog = Adw.AlertDialog(heading=_("“{name}” already exists").format(name=name),
                                 body=_("An item with the same name already exists in this location."))
        apply_all = Gtk.CheckButton(label=_("Apply to all"))
        dialog.set_extra_child(apply_all)
        dialog.add_response("skip", _("Skip"))
        dialog.add_response("keep", _("Keep Both"))
        dialog.add_response("replace", _("Replace"))
        dialog.set_response_appearance("replace", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("skip")

        def on_response(_dialog, response):
            answer.update(response=response, all=apply_all.get_active())
            answered.set()

        dialog.connect("response", on_response)
        dialog.present(window)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(show)
    while not answered.wait(0.2):
        if operation.cancellable.is_cancelled():
            return "skip", True
    return answer["response"], answer["all"]


def transfer(window, uris, directory, move, record=True, on_done=None):
    """Copy or move files into ``directory`` with progress, conflicts and undo."""
    sources = [Gio.File.new_for_uri(uri) for uri in uris]
    count = len(sources)
    if not count:
        return
    title = (ngettext("Moving {n} item", "Moving {n} items", count) if move
             else ngettext("Copying {n} item", "Copying {n} items", count)).format(n=count)

    def work(operation, errors):
        pairs, policy = [], None
        for index, source in enumerate(sources):
            if operation.cancellable.is_cancelled():
                break
            name = source.get_basename()
            operation.update(detail=_("{current} of {total} — {name}").format(current=index + 1, total=count,
                                                                             name=name),
                             fraction=index / count)
            try:
                if source.equal(directory) or directory.has_prefix(source):
                    errors.append(f"{name}: " + _("cannot copy a folder into itself"))
                    continue
                parent = source.get_parent()
                same_folder = parent is not None and parent.equal(directory)
                if move and same_folder:
                    continue
                destination = directory.get_child(name)
                if destination.query_exists(None):
                    if same_folder:
                        destination = unique_child(directory, name)  # duplicate
                    else:
                        choice = policy
                        if choice is None:
                            choice, apply_all = ask_conflict(window, operation, name)
                            if apply_all:
                                policy = choice
                        if choice == "skip":
                            continue
                        if choice == "keep":
                            destination = unique_child(directory, name)
                        else:
                            try:
                                destination.trash(operation.cancellable)
                            except GLib.Error:
                                _delete_recursive(destination, operation.cancellable)

                def progress(current, total, *_args, index=index):
                    operation.update(fraction=(index + (current / total if total else 0)) / count)

                if move:
                    _move_one(source, destination, operation.cancellable, progress)
                else:
                    _copy_recursive(source, destination, operation.cancellable, progress)
                pairs.append((source, destination))
            except GLib.Error as err:
                if _io_error(err, Gio.IOErrorEnum.CANCELLED):
                    break
                errors.append(f"{name}: {err.message}")
        return pairs

    def finished(pairs, errors):
        pairs = pairs or []
        if move:
            for source, destination in pairs:
                if source.get_path() and destination.get_path():
                    window.tagstore.moved(source.get_path(), destination.get_path())
        if errors:
            window.toast(_("Some items could not be copied: {error}").format(error=errors[0]))
        if pairs:
            done = len(pairs)
            if move:
                message = ngettext("{n} item moved", "{n} items moved", done).format(n=done)
                undo = lambda w: move_back(w, pairs)  # noqa: E731
            else:
                message = ngettext("{n} item copied", "{n} items copied", done).format(n=done)
                undo = lambda w: trash_files(w, [d for _s, d in pairs], record=False)  # noqa: E731
            undoable = record and push_undo(window, _("Move") if move else _("Copy"), undo)
            if not on_done:
                window.toast(message, undo=bool(undoable))
        if on_done:
            on_done(pairs)

    _run(window, title, work, finished)


def move_back(window, pairs):
    def work(operation, errors):
        for index, (source, destination) in enumerate(pairs):
            operation.update(detail=source.get_basename(), fraction=index / len(pairs))
            try:
                target = source
                if target.query_exists(None):
                    target = unique_child(source.get_parent(), source.get_basename())
                _move_one(destination, target, operation.cancellable)
                if destination.get_path() and target.get_path():
                    GLib.idle_add(window.tagstore.moved, destination.get_path(), target.get_path())
            except GLib.Error as err:
                errors.append(err.message)

    _run(window, _("Moving Back"), work, lambda _r, errors: window.toast(errors[0]) if errors else None)
