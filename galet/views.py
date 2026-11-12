"""The three Finder views: icons, list and columns."""

import weakref

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from . import dnd
from .i18n import _
from .model import DirectoryModel, FileItem, make_sorter
from .folders import effective_color
from .folders import icon_path as folder_icon_path
from .thumbnails import THUMBNAILER
from .widgets import TagDots

ICON_SIZE_GRID = 64
PREVIEW_IMAGE_MAX_BYTES = 40 * 1024 * 1024


def format_date(timestamp):
    if not timestamp:
        return "—"
    date = GLib.DateTime.new_from_unix_local(timestamp)
    now = GLib.DateTime.new_now_local()
    time = date.format("%H:%M")
    if date.get_ymd() == now.get_ymd():
        return _("Today at {time}").format(time=time)
    if date.get_ymd() == now.add_days(-1).get_ymd():
        return _("Yesterday at {time}").format(time=time)
    return date.format("%e %b %Y, %H:%M").strip()


def format_size(item):
    return "—" if item.is_dir else GLib.format_size(item.size)


def display_label(item, settings):
    """File name as shown, honouring the "show all filename extensions" option."""
    if item.is_dir or settings.get("show_extensions") or "." not in item.name[1:]:
        return item.name
    return item.name.rsplit(".", 1)[0]


SORT_KEYS = {
    "name": None,
    "kind": lambda i: i.kind.casefold(),
    "date": lambda i: -i.mtime,
    "size": lambda i: -i.size,
    "tags": lambda i: (0, i.tags[0].casefold()) if i.tags else (1, ""),
}


def view_sorter(settings):
    """Sorter for icon, column and gallery views ("Sort By" menu)."""
    return make_sorter(SORT_KEYS.get(settings.get("sort_by", "name")), folders_first=settings.get("folders_first"))


FOLDER_STYLE = {"settings": None, "tagstore": None}  # set by the application at startup


def set_item_image(image, item, size):
    color = item.folder_color
    if item.is_dir and FOLDER_STYLE["settings"] is not None:
        color = effective_color(item, FOLDER_STYLE["settings"], FOLDER_STYLE["tagstore"])
    if color:
        image.set_from_file(folder_icon_path(color))
        return
    if not item.thumbnail and size >= 32:
        THUMBNAILER.request(item)  # the cell refreshes when the thumbnail is ready
    if item.thumbnail and size >= 32:
        image.set_from_file(item.thumbnail)
    elif item.icon is not None:
        image.set_from_gicon(item.icon)
    else:
        image.set_from_icon_name("text-x-generic")


# --------------------------------------------------------------------- cells

class _Cell(Gtk.Box):
    """A row/tile bound to a FileItem; redraws itself when the item changes."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.item = None
        self.list_item_ref = None
        self.drop_target = None
        self._handler = 0

    def bind(self, item):
        self.item = item
        self._handler = item.connect("changed", lambda *_a: self._update())
        self._update()

    def _update(self):
        self.refresh()
        if self.drop_target is not None:
            # Only folders accept drops; on files the drop falls through to the
            # view background (= current folder).
            self.drop_target.set_actions(dnd.ACTIONS if self.item.is_dir else dnd.NO_ACTION)

    def unbind(self):
        if self.item is not None and self._handler:
            self.item.disconnect(self._handler)
        self.item = None
        self._handler = 0

    def position(self):
        list_item = self.list_item_ref() if self.list_item_ref else None
        return list_item.get_position() if list_item is not None else Gtk.INVALID_LIST_POSITION

    def refresh(self):
        pass


class GridCell(_Cell):
    def __init__(self, tagstore, settings):
        icon_size = int(settings.get("icon_size", ICON_SIZE_GRID))
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, width_request=max(96, icon_size + 40))
        self.settings = settings
        self.icon_size = icon_size
        self.image = Gtk.Image(pixel_size=icon_size)
        self.label = Gtk.Label(wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR, lines=2,
                               ellipsize=Pango.EllipsizeMode.MIDDLE, justify=Gtk.Justification.CENTER,
                               max_width_chars=14)
        self.dots = TagDots(tagstore, 9)
        name_row = Gtk.Box(spacing=3, halign=Gtk.Align.CENTER)
        name_row.append(self.label)
        name_row.append(self.dots)
        self.append(self.image)
        self.append(name_row)

    def refresh(self):
        set_item_image(self.image, self.item, self.icon_size)
        self.label.set_text(display_label(self.item, self.settings))
        self.dots.set_tags(self.item.tags)
        self.set_opacity(0.55 if self.item.hidden else 1.0)


class NameCell(_Cell):
    def __init__(self, tagstore, settings):
        super().__init__(spacing=8)
        self.settings = settings
        self.image = Gtk.Image(pixel_size=20)
        self.label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.dots = TagDots(tagstore, 10)
        self.append(self.image)
        self.append(self.label)
        self.append(self.dots)

    def refresh(self):
        set_item_image(self.image, self.item, 20)
        self.label.set_text(display_label(self.item, self.settings))
        self.dots.set_tags(self.item.tags)
        self.set_opacity(0.55 if self.item.hidden else 1.0)


class TextCell(_Cell):
    def __init__(self, getter, xalign=0.0):
        super().__init__()
        self.getter = getter
        self.label = Gtk.Label(xalign=xalign, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                               css_classes=["dim-label"])
        self.append(self.label)

    def refresh(self):
        self.label.set_text(self.getter(self.item))


class ColumnRow(_Cell):
    def __init__(self, tagstore, settings):
        super().__init__(spacing=6)
        self.settings = settings
        self.image = Gtk.Image(pixel_size=16)
        self.label = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.dots = TagDots(tagstore, 9)
        self.chevron = Gtk.Image(icon_name="go-next-symbolic", pixel_size=12, css_classes=["dim-label"])
        for widget in (self.image, self.label, self.dots, self.chevron):
            self.append(widget)

    def refresh(self):
        set_item_image(self.image, self.item, 16)
        self.label.set_text(display_label(self.item, self.settings))
        self.dots.set_tags(self.item.tags)
        self.chevron.set_visible(self.item.is_dir)
        self.set_opacity(0.55 if self.item.hidden else 1.0)


def make_factory(create_cell, attach=None):
    factory = Gtk.SignalListItemFactory()

    def setup(_factory, list_item):
        cell = create_cell()
        cell.list_item_ref = weakref.ref(list_item)
        if attach is not None:
            attach(cell)
        list_item.set_child(cell)

    def bind(_factory, list_item):
        list_item.get_child().bind(list_item.get_item())

    def unbind(_factory, list_item):
        list_item.get_child().unbind()

    factory.connect("setup", setup)
    factory.connect("bind", bind)
    factory.connect("unbind", unbind)
    return factory


def secondary_click(widget, handler):
    gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
    gesture.connect("pressed", handler)
    widget.add_controller(gesture)
    return gesture


# ------------------------------------------------------- icon & list views

class _SelectionView:
    """Shared behaviour of the icon and list views (mixin)."""

    def _setup_common(self, pane):
        self.pane = pane
        self.selection.connect("selection-changed", lambda *_a: self.emit("selection-changed"))
        self.view.connect("activate", self._on_activate)
        secondary_click(self.view, self._on_background_menu)
        dnd.add_drop_target(self.view, pane.current_dir, pane.window.drop_files)
        self._place_view()

    def _place_view(self):
        self.set_child(self.view)

    def attach_cell(self, cell):
        if not hasattr(self, "_cells"):
            self._cells = []
        self._cells.append(weakref.ref(cell))
        folder = lambda: cell.item.target_file if cell.item is not None and cell.item.is_dir else None  # noqa: E731
        secondary_click(cell, lambda g, n, x, y: self._on_cell_menu(g, x, y, cell))
        dnd.add_drag_source(cell, lambda: self._drag_files(cell), self.pane.drag_started, self.pane.drag_finished)
        cell.drop_target = dnd.add_drop_target(cell, folder, self.pane.window.drop_files)
        dnd.add_spring_load(cell, folder, self.pane.spring_open)

    def find_cell(self, item):
        for ref in getattr(self, "_cells", []):
            cell = ref()
            if cell is not None and cell.item is item and hasattr(cell, "label") and not isinstance(cell, TextCell):
                return cell
        return None

    def _scroll_to(self, position):
        self.view.scroll_to(position, Gtk.ListScrollFlags.SELECT | Gtk.ListScrollFlags.FOCUS, None)

    def select_prefix(self, prefix):
        for position in range(self.selection.get_n_items()):
            if self.selection.get_item(position).search_key.startswith(prefix):
                self._scroll_to(position)
                return True
        return False

    def select_file(self, gfile):
        for position in range(self.selection.get_n_items()):
            if self.selection.get_item(position).gfile.equal(gfile):
                self._scroll_to(position)
                return True
        return False

    def _drag_files(self, cell):
        position = cell.position()
        if position == Gtk.INVALID_LIST_POSITION:
            return []
        if not self.selection.is_selected(position):
            self.selection.select_item(position, True)
        return [item.gfile for item in self.get_selected_items()]

    def _on_cell_menu(self, gesture, x, y, cell):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        position = cell.position()
        if position == Gtk.INVALID_LIST_POSITION:
            return
        if not self.selection.is_selected(position):
            self.selection.select_item(position, True)
        self.pane.popup_context_menu(cell, x, y, on_item=True)

    def _on_background_menu(self, gesture, _n, x, y):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.selection.unselect_all()
        self.pane.popup_context_menu(self.view, x, y, on_item=False)

    def _on_activate(self, _view, position):
        item = self.selection.get_item(position)
        if item is not None:
            self.emit("activate-item", item)

    def get_selected_items(self):
        bitset = self.selection.get_selection()
        items = (self.selection.get_item(bitset.get_nth(i)) for i in range(bitset.get_size()))
        return [item for item in items if item is not None]

    def focus_view(self):
        self.view.grab_focus()

    def teardown(self):
        pass


class IconGridView(_SelectionView, Gtk.ScrolledWindow):
    __gsignals__ = {
        "activate-item": (GObject.SignalFlags.RUN_FIRST, None, (FileItem,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, pane, model):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        settings = pane.settings
        self.sorted = Gtk.SortListModel(model=model, sorter=view_sorter(settings))
        self.selection = Gtk.MultiSelection(model=self.sorted)
        tagstore = pane.tagstore
        self.view = Gtk.GridView(model=self.selection, max_columns=64, enable_rubberband=True,
                                 factory=make_factory(lambda: GridCell(tagstore, settings), self.attach_cell))
        self.view.add_css_class("galet-grid")
        self._setup_common(pane)


class DetailListView(_SelectionView, Gtk.ScrolledWindow):
    __gsignals__ = {
        "activate-item": (GObject.SignalFlags.RUN_FIRST, None, (FileItem,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, pane, model):
        super().__init__()
        tagstore = pane.tagstore
        settings = pane.settings
        folders_first = settings.get("folders_first")
        self.view = Gtk.ColumnView(enable_rubberband=True, reorderable=False)
        self.view.add_css_class("data-table")

        def column(title, create_cell, sorter, expand=False, width=-1):
            col = Gtk.ColumnViewColumn(title=title, factory=make_factory(create_cell, self.attach_cell),
                                       expand=expand, resizable=True, sorter=sorter)
            if width > 0:
                col.set_fixed_width(width)
            self.view.append_column(col)
            return col

        name_col = column(_("Name"), lambda: NameCell(tagstore, settings),
                          make_sorter(folders_first=folders_first), expand=True)
        column(_("Date Modified"), lambda: TextCell(lambda i: format_date(i.mtime)),
               make_sorter(lambda i: i.mtime), width=190)
        column(_("Size"), lambda: TextCell(format_size, xalign=1.0),
               make_sorter(lambda i: (not i.is_dir, i.size)), width=100)
        column(_("Kind"), lambda: TextCell(lambda i: i.kind),
               make_sorter(lambda i: i.kind.casefold()), width=170)
        if pane.location.is_virtual:
            # Search results and tag views mix folders: show where each file is.
            def where(item):
                parent = item.gfile.get_parent()
                path = parent.get_path() if parent is not None else None
                home = GLib.get_home_dir()
                if path and (path == home or path.startswith(home + "/")):
                    path = "~" + path[len(home):]
                return path or (parent.get_uri() if parent is not None else "")

            column(_("Location"), lambda: TextCell(where), make_sorter(lambda i: where(i).casefold()), width=260)

        self.sorted = Gtk.SortListModel(model=model, sorter=self.view.get_sorter())
        group_key = GROUPS.get(settings.get("group_by", "none"))
        if group_key is not None:
            key = (lambda item: group_key(item, tagstore))
            self.sorted.set_section_sorter(make_sorter(lambda item: key(item)[0], tie_break=False))
            header = Gtk.SignalListItemFactory()
            header.connect("setup", lambda _f, h: h.set_child(
                Gtk.Label(xalign=0, css_classes=["heading", "galet-group-header"])))
            header.connect("bind", lambda _f, h: h.get_child().set_text(key(h.get_item())[1]))
            self.view.set_header_factory(header)
        self.selection = Gtk.MultiSelection(model=self.sorted)
        self.view.set_model(self.selection)
        self.view.sort_by_column(name_col, Gtk.SortType.ASCENDING)
        self._setup_common(pane)

    def _scroll_to(self, position):
        self.view.scroll_to(position, None, Gtk.ListScrollFlags.SELECT | Gtk.ListScrollFlags.FOCUS, None)


# ------------------------------------------------------------------ grouping

ARCHIVE_TYPES = ("application/zip", "application/x-tar", "application/x-7z-compressed", "application/vnd.rar",
                 "application/x-rar", "application/gzip", "application/x-compressed-tar", "application/x-xz",
                 "application/x-bzip")
DOCUMENT_HINTS = ("pdf", "opendocument", "msword", "officedocument", "ms-excel", "ms-powerpoint", "rtf",
                  "epub")


def group_by_kind(item, _tagstore):
    content = item.content_type
    if item.is_dir:
        return 0, _("Folders")
    if content.startswith("image/"):
        return 1, _("Images")
    if content.startswith("video/"):
        return 2, _("Videos")
    if content.startswith("audio/"):
        return 3, _("Music")
    if content.startswith("text/") or any(hint in content for hint in DOCUMENT_HINTS):
        return 4, _("Documents")
    if any(Gio.content_type_is_a(content, t) for t in ARCHIVE_TYPES):
        return 5, _("Archives")
    if content in ("application/x-executable", "application/x-desktop", "application/vnd.appimage",
                   "application/x-shellscript", "application/vnd.debian.binary-package"):
        return 6, _("Applications")
    return 7, _("Other")


def group_by_date(item, _tagstore):
    if not item.mtime:
        return 99999, _("Unknown")
    now = GLib.DateTime.new_now_local()
    date = GLib.DateTime.new_from_unix_local(item.mtime)
    today = GLib.DateTime.new_local(now.get_year(), now.get_month(), now.get_day_of_month(), 0, 0, 0)
    age_days = (today.to_unix() - item.mtime) / 86400
    if age_days <= 0:
        return 0, _("Today")
    if age_days <= 1:
        return 1, _("Yesterday")
    if age_days <= 7:
        return 2, _("Previous 7 Days")
    if age_days <= 30:
        return 3, _("Previous 30 Days")
    if date.get_year() == now.get_year():
        return 4, _("Earlier This Year")
    return 5 + now.get_year() - date.get_year(), str(date.get_year())


def group_by_tags(item, tagstore):
    names = [t["name"] for t in tagstore.tags]
    if not item.tags:
        return 10000, _("No Tags")
    first = item.tags[0]
    return (names.index(first) if first in names else 9999), first


GROUPS = {"kind": group_by_kind, "date": group_by_date, "tags": group_by_tags}


# ------------------------------------------------ grouped icon view (sections)

class _IconSection(_SelectionView, Gtk.Box):
    """One group (header + grid) of the grouped icon view."""

    __gsignals__ = {
        "activate-item": (GObject.SignalFlags.RUN_FIRST, None, (FileItem,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, pane, model, key, key_of):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.key = key
        settings, tagstore = pane.settings, pane.tagstore
        group_filter = Gtk.CustomFilter.new(lambda item, *_a: key_of(item) == key)
        self.sorted = Gtk.SortListModel(model=Gtk.FilterListModel(model=model, filter=group_filter),
                                        sorter=view_sorter(settings))
        self.selection = Gtk.MultiSelection(model=self.sorted)
        self.view = Gtk.GridView(model=self.selection, max_columns=64, enable_rubberband=True,
                                 factory=make_factory(lambda: GridCell(tagstore, settings), self.attach_cell))
        self.view.add_css_class("galet-grid")
        self.view.set_vexpand(False)
        self.set_vexpand(False)
        self.header = Gtk.Label(label=key[1], xalign=0, css_classes=["heading", "galet-group-header"])
        self._setup_common(pane)

    def _place_view(self):
        self.append(self.header)
        self.append(self.view)


class GroupedIconView(Gtk.ScrolledWindow):
    """Icon view split into sections (kind, date or tag), like Finder's "Use Groups"."""

    __gsignals__ = {
        "activate-item": (GObject.SignalFlags.RUN_FIRST, None, (FileItem,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, pane, model, group):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.pane = pane
        self.model = model
        self.key_of = lambda item: group(item, pane.tagstore)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.START)
        self.set_child(self.box)
        self.sections = {}
        self._source = 0
        self._busy = False
        self._columns = 0
        icon_size = int(pane.settings.get("icon_size", ICON_SIZE_GRID))
        self._cell_width = max(96, icon_size + 40) + 16
        model.connect("items-changed", lambda *_a: self._queue())
        secondary_click(self, lambda _g, _n, x, y: pane.popup_context_menu(self, x, y, on_item=False))
        dnd.add_drop_target(self, pane.current_dir, pane.window.drop_files)
        self._rebuild()

    def do_size_allocate(self, width, height, baseline):
        Gtk.ScrolledWindow.do_size_allocate(self, width, height, baseline)
        # GridView sizes itself as if it had one column when it is not scrollable:
        # tell each section how many columns really fit so it gets the right height.
        columns = max(1, (width - 24) // self._cell_width)
        if columns != self._columns:
            self._columns = columns
            GLib.idle_add(self._apply_columns)

    def _apply_columns(self):
        for section in self.sections.values():
            section.view.set_min_columns(self._columns)
            section.view.set_max_columns(self._columns)
        return GLib.SOURCE_REMOVE

    def _queue(self):
        if not self._source:
            self._source = GLib.timeout_add(80, self._rebuild)

    def _rebuild(self):
        self._source = 0
        keys = {self.key_of(self.model.get_item(i)) for i in range(self.model.get_n_items())}
        for key in [k for k in self.sections if k not in keys]:
            self.box.remove(self.sections.pop(key))
        for key in sorted(keys):
            if key not in self.sections:
                section = _IconSection(self.pane, self.model, key, self.key_of)
                section.connect("activate-item", lambda _s, item: self.emit("activate-item", item))
                section.connect("selection-changed", self._on_section_selection)
                if self._columns:
                    section.view.set_min_columns(self._columns)
                    section.view.set_max_columns(self._columns)
                self.sections[key] = section
        # Keep sections in group order.
        previous = None
        for key in sorted(self.sections):
            section = self.sections[key]
            if section.get_parent() is None:
                self.box.insert_child_after(section, previous)
            else:
                self.box.reorder_child_after(section, previous)
            previous = section
        return GLib.SOURCE_REMOVE

    def _on_section_selection(self, section):
        if self._busy:
            return
        if section.get_selected_items():
            self._busy = True
            for other in self.sections.values():
                if other is not section:
                    other.selection.unselect_all()
            self._busy = False
        self.emit("selection-changed")

    def _ordered(self):
        return [self.sections[k] for k in sorted(self.sections)]

    def get_selected_items(self):
        return [item for section in self._ordered() for item in section.get_selected_items()]

    def select_prefix(self, prefix):
        return any(section.select_prefix(prefix) for section in self._ordered())

    def select_file(self, gfile):
        return any(section.select_file(gfile) for section in self._ordered())

    def find_cell(self, item):
        for section in self._ordered():
            cell = section.find_cell(item)
            if cell is not None:
                return cell
        return None

    def focus_view(self):
        sections = self._ordered()
        if sections:
            sections[0].focus_view()

    def teardown(self):
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0


# ------------------------------------------------------------------- gallery

class GalleryThumb(_Cell):
    def __init__(self, tagstore, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=96)
        self.settings = settings
        self.image = Gtk.Image(pixel_size=72)
        self.label = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=12,
                               css_classes=["caption"])
        self.dots = TagDots(tagstore, 8)
        self.dots.set_halign(Gtk.Align.CENTER)
        self.append(self.image)
        self.append(self.label)
        self.append(self.dots)

    def refresh(self):
        set_item_image(self.image, self.item, 72)
        self.label.set_text(display_label(self.item, self.settings))
        self.dots.set_tags(self.item.tags)


class GalleryView(_SelectionView, Gtk.Box):
    """Finder's Gallery view: a large preview above a strip of thumbnails."""

    __gsignals__ = {
        "activate-item": (GObject.SignalFlags.RUN_FIRST, None, (FileItem,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, pane, model):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        settings = pane.settings
        tagstore = pane.tagstore
        self.sorted = Gtk.SortListModel(model=model, sorter=view_sorter(settings))
        self.selection = Gtk.SingleSelection(model=self.sorted, autoselect=True, can_unselect=False)
        self.view = Gtk.ListView(model=self.selection, orientation=Gtk.Orientation.HORIZONTAL,
                                 factory=make_factory(lambda: GalleryThumb(tagstore, settings), self.attach_cell))
        self.view.add_css_class("galet-gallery-strip")
        self.stage = Adw.Bin(vexpand=True, hexpand=True, margin_top=12, margin_start=24, margin_end=24)
        self.caption = Gtk.Label(css_classes=["title-4"], ellipsize=Pango.EllipsizeMode.MIDDLE, margin_top=8)
        self.details = Gtk.Label(css_classes=["dim-label", "caption"], margin_bottom=8)
        self.selection.connect("selection-changed", lambda *_a: self._update_stage())
        self.sorted.connect("items-changed", lambda *_a: self._update_stage())
        self._shown = None
        self._setup_common(pane)

    def _place_view(self):
        strip = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, height_request=128)
        strip.set_child(self.view)
        self.append(self.stage)
        self.append(self.caption)
        self.append(self.details)
        self.append(Gtk.Separator())
        self.append(strip)

    def _update_stage(self):
        from .info import build_preview, image_dimensions

        item = self.selection.get_selected_item()
        if item is self._shown:
            return
        self._shown = item
        if item is None:
            self.stage.set_child(None)
            self.caption.set_text("")
            self.details.set_text("")
            return
        self.stage.set_child(build_preview(item, height=320, interactive=True))
        self.caption.set_text(item.name)
        parts = [item.kind, format_size(item), format_date(item.mtime)]
        dimensions = image_dimensions(item)
        if dimensions:
            parts.insert(1, dimensions)
        self.details.set_text(" · ".join(parts))

    def _scroll_to(self, position):
        self.view.scroll_to(position, Gtk.ListScrollFlags.SELECT | Gtk.ListScrollFlags.FOCUS, None)


# -------------------------------------------------------------- column view

class PreviewPanel(Gtk.Box):
    """Last column of the column view: a big preview and file details."""

    def __init__(self, item, tagstore):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, width_request=280,
                         valign=Gtk.Align.START, css_classes=["galet-preview"])
        if (item.content_type.startswith("image/") and item.path
                and item.size <= PREVIEW_IMAGE_MAX_BYTES):
            picture = Gtk.Picture(file=item.gfile, can_shrink=True, height_request=200,
                                  content_fit=Gtk.ContentFit.CONTAIN)
            self.append(picture)
        else:
            image = Gtk.Image(pixel_size=128)
            set_item_image(image, item, 128)
            self.append(image)

        title = Gtk.Label(label=item.name, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                          justify=Gtk.Justification.CENTER, css_classes=["title-4"], margin_top=8)
        self.append(title)
        self.append(Gtk.Label(label=f"{item.kind} — {format_size(item)}", css_classes=["dim-label"]))

        dots = TagDots(tagstore, 12, max_dots=8)
        dots.set_tags(item.tags)
        dots.set_halign(Gtk.Align.CENTER)
        self.append(dots)

        grid = Gtk.Grid(column_spacing=12, row_spacing=4, margin_top=12, halign=Gtk.Align.CENTER)
        rows = [(_("Modified"), format_date(item.mtime))]
        if item.tags:
            rows.append((_("Tags"), ", ".join(item.tags)))
        for row, (key, value) in enumerate(rows):
            grid.attach(Gtk.Label(label=key, xalign=1, css_classes=["dim-label", "caption"]), 0, row, 1, 1)
            grid.attach(Gtk.Label(label=value, xalign=0, wrap=True, css_classes=["caption"]), 1, row, 1, 1)
        self.append(grid)


class _Column:
    __slots__ = ("gfile", "model", "selection", "view", "scroller", "current")


class ColumnBrowser(Gtk.ScrolledWindow):
    """Miller columns: each selected folder opens a new column to the right."""

    __gsignals__ = {
        "activate-item": (GObject.SignalFlags.RUN_FIRST, None, (FileItem,)),
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "directory-changed": (GObject.SignalFlags.RUN_FIRST, None, (Gio.File,)),
    }

    def __init__(self, pane, root):
        super().__init__(vscrollbar_policy=Gtk.PolicyType.NEVER)
        self.pane = pane
        self.columns = []
        self._cells = []
        self.preview = None
        self.box = Gtk.Box()
        self.set_child(self.box)
        self._add_column(root)

    # columns ---------------------------------------------------------------

    def _add_column(self, gfile):
        col = _Column()
        col.gfile = gfile
        col.current = None
        col.model = DirectoryModel(gfile, self.pane.tagstore)
        filtered = Gtk.FilterListModel(model=col.model.store, filter=self.pane.filter)
        settings = self.pane.settings
        ordered = Gtk.SortListModel(model=filtered, sorter=view_sorter(settings))
        col.selection = Gtk.SingleSelection(model=ordered, autoselect=False, can_unselect=True)
        tagstore = self.pane.tagstore
        col.view = Gtk.ListView(model=col.selection,
                                factory=make_factory(lambda: ColumnRow(tagstore, settings),
                                                     lambda cell: self._attach_cell(cell, col)))
        col.view.add_css_class("galet-column-list")
        col.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=240,
                                          css_classes=["galet-column"])
        col.scroller.set_child(col.view)

        col.selection.connect("selection-changed", lambda *_a: self._on_selected(col))
        col.view.connect("activate", lambda _v, pos: self._on_activate(col, pos))
        secondary_click(col.view, lambda g, n, x, y: self._on_background_menu(col, x, y))
        dnd.add_drop_target(col.view, lambda: col.gfile, self.pane.window.drop_files)
        keys = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", lambda c, keyval, code, state: self._on_key(col, keyval, state))
        col.view.add_controller(keys)

        self.columns.append(col)
        self.box.append(col.scroller)
        return col

    def _truncate_after(self, col):
        index = self.columns.index(col)
        for extra in self.columns[index + 1:]:
            extra.model.close()
            self.box.remove(extra.scroller)
        del self.columns[index + 1:]
        if self.preview is not None:
            self.box.remove(self.preview)
            self.preview = None

    def _on_selected(self, col):
        if col not in self.columns:
            return
        item = col.selection.get_selected_item()
        previous = col.current
        if (item is not None and previous is not None and item.gfile.equal(previous.gfile)
                and len(self.columns) > self.columns.index(col) + (1 if item.is_dir else 0)):
            return
        col.current = item
        self._truncate_after(col)
        if item is not None:
            if item.is_dir:
                self._add_column(item.target_file)
            else:
                self.preview = PreviewPanel(item, self.pane.tagstore)
                self.box.append(self.preview)
        self.emit("directory-changed", self.columns[-1].gfile)
        self.emit("selection-changed")
        GLib.timeout_add(60, self._scroll_to_end)

    def _scroll_to_end(self):
        adjustment = self.get_hadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        return GLib.SOURCE_REMOVE

    def _on_activate(self, col, position):
        item = col.selection.get_item(position)
        if item is not None and not item.is_dir:
            self.emit("activate-item", item)

    def _on_key(self, col, keyval, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        index = self.columns.index(col)
        if keyval == Gdk.KEY_Right and index + 1 < len(self.columns):
            following = self.columns[index + 1]
            if following.selection.get_n_items():
                position = following.selection.get_selected()
                if position == Gtk.INVALID_LIST_POSITION:
                    position = 0
                following.view.scroll_to(position, Gtk.ListScrollFlags.FOCUS | Gtk.ListScrollFlags.SELECT,
                                         None)
            return True
        if keyval == Gdk.KEY_Left and index > 0:
            previous = self.columns[index - 1]
            col.selection.unselect_all()
            position = previous.selection.get_selected()
            if position != Gtk.INVALID_LIST_POSITION:
                previous.view.scroll_to(position, Gtk.ListScrollFlags.FOCUS, None)
            return True
        return False

    # context menus ---------------------------------------------------------

    def _attach_cell(self, cell, col):
        self._cells.append(weakref.ref(cell))
        folder = lambda: cell.item.target_file if cell.item is not None and cell.item.is_dir else None  # noqa: E731
        secondary_click(cell, lambda g, n, x, y: self._on_cell_menu(g, x, y, cell, col))
        dnd.add_drag_source(cell, lambda: self._drag_files(cell, col), self.pane.drag_started,
                            self.pane.drag_finished)
        cell.drop_target = dnd.add_drop_target(cell, folder, self.pane.window.drop_files)

        def spring(_folder):
            position = cell.position()
            if col in self.columns and position != Gtk.INVALID_LIST_POSITION:
                col.selection.set_selected(position)

        dnd.add_spring_load(cell, folder, spring)

    def _active_column(self):
        for col in self.columns:
            focus = col.view.get_root().get_focus() if col.view.get_root() else None
            if focus is not None and (focus is col.view or focus.is_ancestor(col.view)):
                return col
        return self.columns[-1]

    def select_prefix(self, prefix):
        col = self._active_column()
        for position in range(col.selection.get_n_items()):
            if col.selection.get_item(position).search_key.startswith(prefix):
                col.view.scroll_to(position, Gtk.ListScrollFlags.SELECT | Gtk.ListScrollFlags.FOCUS, None)
                return True
        return False

    def select_file(self, gfile):
        for col in reversed(self.columns):
            if gfile.get_parent() is not None and gfile.get_parent().equal(col.gfile):
                for position in range(col.selection.get_n_items()):
                    if col.selection.get_item(position).gfile.equal(gfile):
                        col.view.scroll_to(position, Gtk.ListScrollFlags.SELECT | Gtk.ListScrollFlags.FOCUS,
                                           None)
                        return True
        return False

    def find_cell(self, item):
        for ref in self._cells:
            cell = ref()
            if cell is not None and cell.item is item:
                return cell
        return None

    def _drag_files(self, cell, col):
        position = cell.position()
        if position == Gtk.INVALID_LIST_POSITION or col not in self.columns:
            return []
        if col.selection.get_selected() != position:
            col.selection.set_selected(position)
        item = col.selection.get_selected_item()
        return [item.gfile] if item is not None else []

    def _on_cell_menu(self, gesture, x, y, cell, col):
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        position = cell.position()
        if position != Gtk.INVALID_LIST_POSITION and col in self.columns:
            col.selection.set_selected(position)
            self.pane.popup_context_menu(cell, x, y, on_item=True)

    def _on_background_menu(self, col, x, y):
        if col in self.columns:
            col.selection.unselect_all()
            self.pane.popup_context_menu(col.view, x, y, on_item=False)

    # pane interface --------------------------------------------------------

    def current_dir(self):
        return self.columns[-1].gfile

    def get_selected_items(self):
        for col in reversed(self.columns):
            item = col.selection.get_selected_item()
            if item is not None:
                return [item]
        return []

    def focus_view(self):
        self.columns[-1].view.grab_focus()

    def teardown(self):
        for col in self.columns:
            col.model.close()
