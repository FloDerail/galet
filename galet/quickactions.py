"""Finder-style Quick Actions: rotate, convert, resize, PDF, compress, extract."""

import os
import shutil
import subprocess
import zipfile

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib  # noqa: E402

from . import fileops  # noqa: E402
from .i18n import _, ngettext  # noqa: E402

IMAGE_TYPES = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp", "image/bmp": "bmp",
               "image/tiff": "tiff"}
ARCHIVE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz",
                    ".7z", ".rar", ".gz", ".bz2", ".xz")
SIZES = {"small": 640, "medium": 1280, "large": 1920}


def _local(items):
    return [i for i in items if i.path]


def images(items):
    return [i for i in _local(items) if i.content_type in IMAGE_TYPES]


def archives(items):
    return [i for i in _local(items) if not i.is_dir and i.name.lower().endswith(ARCHIVE_SUFFIXES)]


def menu_entries(items):
    """(label, action) pairs that apply to the selection, for the context menu."""
    entries = []
    if images(items) and len(images(items)) == len(items):
        entries += [(_("Rotate Left"), "win.quick-action::rotate-left"),
                    (_("Rotate Right"), "win.quick-action::rotate-right"),
                    (_("Convert to JPEG"), "win.quick-action::to-jpeg"),
                    (_("Convert to PNG"), "win.quick-action::to-png"),
                    (_("Reduce Size"), "win.quick-action::resize-medium"),
                    (_("Create PDF"), "win.quick-action::pdf")]
    if archives(items) and len(archives(items)) == len(items):
        entries.append((_("Extract Here"), "win.quick-action::extract"))
    if _local(items):
        entries.append((_("Compress"), "win.quick-action::compress"))
    return entries


def run(window, action, items):
    handlers = {
        "rotate-left": lambda: _rotate(window, images(items), GdkPixbuf.PixbufRotation.COUNTERCLOCKWISE),
        "rotate-right": lambda: _rotate(window, images(items), GdkPixbuf.PixbufRotation.CLOCKWISE),
        "to-jpeg": lambda: _convert(window, images(items), "jpeg", ".jpg"),
        "to-png": lambda: _convert(window, images(items), "png", ".png"),
        "resize-small": lambda: _resize(window, images(items), SIZES["small"]),
        "resize-medium": lambda: _resize(window, images(items), SIZES["medium"]),
        "resize-large": lambda: _resize(window, images(items), SIZES["large"]),
        "pdf": lambda: _pdf(window, images(items)),
        "compress": lambda: _compress(window, _local(items)),
        "extract": lambda: _extract(window, archives(items)),
    }
    handler = handlers.get(action)
    if handler is not None:
        handler()


# ------------------------------------------------------------------- helpers

def _save(pixbuf, path, kind):
    options = (["quality"], ["94"]) if kind == "jpeg" else ([], [])
    tmp = path + ".galet-tmp"
    pixbuf.savev(tmp, kind, *options)
    os.replace(tmp, path)


def _load(path):
    pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
    return pixbuf.apply_embedded_orientation() or pixbuf


def _stem(name):
    return name.rsplit(".", 1)[0] if "." in name[1:] else name


def _created(window, files, label):
    """Report new files and make them undoable (moved to the trash)."""
    if not files:
        return
    gfiles = [Gio.File.new_for_path(p) for p in files]
    undoable = fileops.push_undo(window, label, lambda w: fileops.trash_files(w, gfiles, record=False))
    count = len(files)
    window.toast(ngettext("{n} file created", "{n} files created", count).format(n=count), undo=undoable)
    window.current_pane.reveal(gfiles[0])


def _report(window, errors):
    if errors:
        window.toast(_("Some items could not be processed: {error}").format(error=errors[0]))


# -------------------------------------------------------------------- images

def _rotate(window, items, rotation):
    def work(operation, errors):
        for index, item in enumerate(items):
            operation.update(detail=item.name, fraction=index / len(items))
            try:
                pixbuf = _load(item.path).rotate_simple(rotation)
                _save(pixbuf, item.path, IMAGE_TYPES[item.content_type])
            except GLib.Error as err:
                errors.append(f"{item.name}: {err.message}")

    fileops._run(window, _("Rotating Images"), work, lambda _r, errors: _report(window, errors))


def _convert(window, items, kind, extension):
    def work(operation, errors):
        created = []
        for index, item in enumerate(items):
            operation.update(detail=item.name, fraction=index / len(items))
            directory = item.gfile.get_parent()
            target = fileops.unique_child(directory, _stem(item.name) + extension).get_path()
            try:
                pixbuf = _load(item.path)
                if kind == "jpeg" and pixbuf.get_has_alpha():
                    pixbuf = pixbuf.composite_color_simple(pixbuf.get_width(), pixbuf.get_height(),
                                                           GdkPixbuf.InterpType.NEAREST, 255, 1,
                                                           0xFFFFFF, 0xFFFFFF)
                _save(pixbuf, target, kind)
                created.append(target)
            except GLib.Error as err:
                errors.append(f"{item.name}: {err.message}")
        return created

    fileops._run(window, _("Converting Images"), work,
                 lambda created, errors: (_report(window, errors), _created(window, created or [], _("Convert"))))


def _resize(window, items, longest_side):
    def work(operation, errors):
        created = []
        for index, item in enumerate(items):
            operation.update(detail=item.name, fraction=index / len(items))
            try:
                pixbuf = _load(item.path)
                width, height = pixbuf.get_width(), pixbuf.get_height()
                scale = min(1.0, longest_side / max(width, height))
                pixbuf = pixbuf.scale_simple(max(1, int(width * scale)), max(1, int(height * scale)),
                                             GdkPixbuf.InterpType.BILINEAR)
                stem, ext = fileops._split_ext(item.name)
                name = _("{name} (reduced){ext}").format(name=stem, ext=ext)
                target = fileops.unique_child(item.gfile.get_parent(), name).get_path()
                _save(pixbuf, target, IMAGE_TYPES[item.content_type])
                created.append(target)
            except GLib.Error as err:
                errors.append(f"{item.name}: {err.message}")
        return created

    fileops._run(window, _("Resizing Images"), work,
                 lambda created, errors: (_report(window, errors), _created(window, created or [], _("Reduce Size"))))


def _pdf(window, items):
    if not items:
        return
    items = sorted(items, key=lambda i: i.sort_key)
    name = (_stem(items[0].name) if len(items) == 1 else _("Images")) + ".pdf"
    target = fileops.unique_child(items[0].gfile.get_parent(), name).get_path()

    def work(operation, errors):
        surface = None
        try:
            for index, item in enumerate(items):
                operation.update(detail=item.name, fraction=index / len(items))
                pixbuf = _load(item.path)
                width, height = pixbuf.get_width(), pixbuf.get_height()
                # Fit each image on an A4 page (points), keeping its orientation.
                page_w, page_h = (595, 842) if height >= width else (842, 595)
                if surface is None:
                    surface = cairo.PDFSurface(target, page_w, page_h)
                else:
                    surface.set_size(page_w, page_h)
                context = cairo.Context(surface)
                scale = min(page_w / width, page_h / height)
                context.translate((page_w - width * scale) / 2, (page_h - height * scale) / 2)
                context.scale(scale, scale)
                png = pixbuf.save_to_bufferv("png", [], [])[1]
                image = cairo.ImageSurface.create_from_png(_BytesReader(png))
                context.set_source_surface(image, 0, 0)
                context.paint()
                context.show_page()
        except (GLib.Error, cairo.Error) as err:
            errors.append(str(err))
            return []
        finally:
            if surface is not None:
                surface.finish()
        return [target]

    fileops._run(window, _("Creating PDF"), work,
                 lambda created, errors: (_report(window, errors), _created(window, created or [], _("Create PDF"))))


class _BytesReader:
    def __init__(self, data):
        self.data, self.offset = bytes(data), 0

    def read(self, size=-1):
        if size < 0:
            size = len(self.data) - self.offset
        chunk = self.data[self.offset:self.offset + size]
        self.offset += len(chunk)
        return chunk


# ------------------------------------------------------------------ archives

def _compress(window, items):
    if not items:
        return
    directory = items[0].gfile.get_parent()
    name = (items[0].name if len(items) == 1 else _("Archive")) + ".zip"
    target = fileops.unique_child(directory, name).get_path()
    base = os.path.dirname(items[0].path)

    def work(operation, errors):
        files = []
        for item in items:
            if os.path.isdir(item.path):
                for root, _dirs, names in os.walk(item.path):
                    files += [os.path.join(root, n) for n in names]
                    if not names:
                        files.append(root)
            else:
                files.append(item.path)
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for index, path in enumerate(files):
                    if operation.cancellable.is_cancelled():
                        raise InterruptedError
                    operation.update(detail=os.path.basename(path), fraction=index / max(1, len(files)))
                    archive.write(path, os.path.relpath(path, base))
        except (OSError, InterruptedError) as err:
            if os.path.exists(target):
                os.remove(target)
            if not isinstance(err, InterruptedError):
                errors.append(str(err))
            return []
        return [target]

    fileops._run(window, _("Compressing"), work,
                 lambda created, errors: (_report(window, errors), _created(window, created or [], _("Compress"))))


def _extract(window, items):
    def work(operation, errors):
        created = []
        for index, item in enumerate(items):
            operation.update(detail=item.name, fraction=index / len(items))
            stem = item.name
            for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
                if stem.lower().endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            target = fileops.unique_child(item.gfile.get_parent(), stem or _("Archive")).get_path()
            try:
                os.makedirs(target)
                try:
                    shutil.unpack_archive(item.path, target)
                except (shutil.ReadError, ValueError):
                    from .sandbox import find_program

                    tool = find_program("7z")
                    if tool is None:
                        raise OSError(_("unsupported archive format"))
                    subprocess.run([*tool, "x", "-y", f"-o{target}", item.path], check=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                _flatten_single_folder(target)
                created.append(target)
            except (OSError, subprocess.CalledProcessError) as err:
                shutil.rmtree(target, ignore_errors=True)
                errors.append(f"{item.name}: {err}")
        return created

    fileops._run(window, _("Extracting"), work,
                 lambda created, errors: (_report(window, errors), _created(window, created or [], _("Extract Here"))))


def _flatten_single_folder(target):
    """"photos.zip" containing only "photos/" gives "photos", not "photos/photos"."""
    entries = os.listdir(target)
    if len(entries) == 1 and os.path.isdir(os.path.join(target, entries[0])) \
            and entries[0] == os.path.basename(target):
        inner = os.path.join(target, entries[0])
        temp = target + ".galet-flatten"
        os.rename(inner, temp)
        os.rmdir(target)
        os.rename(temp, target)
