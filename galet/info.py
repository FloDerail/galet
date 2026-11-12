"""Previews, the side preview panel (Ctrl+Shift+P) and "Get Info" (Ctrl+I)."""

import os
import threading

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from . import quickactions  # noqa: E402
from .i18n import _, ngettext  # noqa: E402
from .widgets import TagDots  # noqa: E402

TEXT_PREVIEW_BYTES = 6000
DIRECT_IMAGE_MAX_BYTES = 25 * 1024 * 1024
XATTR_COMMENT = "user.xdg.comment"


def _format_date(timestamp):
    from .views import format_date

    return format_date(timestamp)


def _format_size(item):
    from .views import format_size

    return format_size(item)


# ------------------------------------------------------------------- preview

def build_preview(item, height=220, interactive=False):
    """Widget showing the content of ``item``: image, video, text or icon."""
    kind = item.content_type
    if kind.startswith("image/") and item.path and item.size <= DIRECT_IMAGE_MAX_BYTES and kind != "image/svg+xml":
        return Gtk.Picture(file=item.gfile, can_shrink=True, content_fit=Gtk.ContentFit.CONTAIN,
                           height_request=height, hexpand=True, vexpand=interactive)
    if interactive and (kind.startswith("video/") or kind.startswith("audio/")) and item.path:
        return Gtk.Video(file=item.gfile, autoplay=False, height_request=height, hexpand=True, vexpand=True)
    if Gio.content_type_is_a(kind, "text/plain") and item.path and not item.is_dir:
        try:
            with open(item.path, "rb") as handle:
                text = handle.read(TEXT_PREVIEW_BYTES).decode("utf-8", "replace")
        except OSError:
            text = None
        if text is not None:
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                left_margin=8, right_margin=8, css_classes=["card"])
            view.get_buffer().set_text(text)
            scroller = Gtk.ScrolledWindow(height_request=height, hexpand=True, vexpand=interactive)
            scroller.set_child(view)
            return scroller
    image = Gtk.Image(pixel_size=min(height, 256), height_request=height)
    if item.thumbnail:
        image.set_from_file(item.thumbnail)
    elif item.icon is not None:
        image.set_from_gicon(item.icon)
    return image


def image_dimensions(item):
    if not item.content_type.startswith("image/") or not item.path:
        return None
    result = GdkPixbuf.Pixbuf.get_file_info(item.path)
    if result and result[0] is not None:
        return f"{result[1]} × {result[2]}"
    return None


def _info_grid(rows):
    grid = Gtk.Grid(column_spacing=12, row_spacing=6, margin_top=12)
    for index, (key, value) in enumerate(rows):
        grid.attach(Gtk.Label(label=key, xalign=1, valign=Gtk.Align.START, css_classes=["dim-label", "caption"]),
                    0, index, 1, 1)
        grid.attach(Gtk.Label(label=value, xalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                              selectable=True, hexpand=True, css_classes=["caption"]), 1, index, 1, 1)
    return grid


class InfoPanel(Gtk.ScrolledWindow):
    """Finder's preview pane: shown on the right of any view."""

    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, width_request=290,
                         css_classes=["galet-info-panel"])
        self.window = window
        self._source = 0
        self._items = None

    def show_items(self, items):
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(120, self._render, list(items))

    def _render(self, items):
        self._source = 0
        if self._items is not None and len(items) == len(self._items) and all(
                a is b for a, b in zip(items, self._items)):
            return GLib.SOURCE_REMOVE
        self._items = items
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=16, margin_bottom=16,
                      margin_start=14, margin_end=14)
        if not items:
            box.append(Gtk.Label(label=_("No Selection"), css_classes=["dim-label"], margin_top=40))
        elif len(items) == 1:
            self._single(box, items[0])
        else:
            total = sum(i.size for i in items if not i.is_dir)
            image = Gtk.Image(icon_name="edit-copy-symbolic", pixel_size=96, css_classes=["dim-label"])
            box.append(image)
            box.append(Gtk.Label(label=ngettext("{n} item", "{n} items", len(items)).format(n=len(items)),
                                 css_classes=["title-4"]))
            box.append(Gtk.Label(label=GLib.format_size(total), css_classes=["dim-label"]))
            self._actions(box, items)
        self.set_child(box)
        return GLib.SOURCE_REMOVE

    def _single(self, box, item):
        box.append(build_preview(item))
        box.append(Gtk.Label(label=item.name, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                             justify=Gtk.Justification.CENTER, css_classes=["title-4"], margin_top=8))
        box.append(Gtk.Label(label=f"{item.kind} — {_format_size(item)}", css_classes=["dim-label"]))
        if item.tags:
            dots = TagDots(self.window.tagstore, 12, max_dots=8)
            dots.set_tags(item.tags)
            dots.set_halign(Gtk.Align.CENTER)
            box.append(dots)
        rows = []
        dimensions = image_dimensions(item)
        if dimensions:
            rows.append((_("Dimensions"), dimensions))
        created = item.info.get_attribute_uint64("time::created") if item.info.has_attribute("time::created") else 0
        if created:
            rows.append((_("Created"), _format_date(created)))
        rows.append((_("Modified"), _format_date(item.mtime)))
        if item.tags:
            rows.append((_("Tags"), ", ".join(item.tags)))
        box.append(_info_grid(rows))
        self._actions(box, [item])

    def _actions(self, box, items):
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2, margin_top=12,
                           column_spacing=6, row_spacing=6, homogeneous=True)
        for label, action in quickactions.menu_entries(items)[:6]:
            button = Gtk.Button(label=label)
            button.set_detailed_action_name(action)
            flow.append(button)
        more = Gtk.Button(label=_("Get Info"), action_name="win.get-info")
        flow.append(more)
        box.append(flow)


# ------------------------------------------------------------------ get info

def _permissions_text(mode):
    def describe(bits):
        readable, writable = bits & 4, bits & 2
        if readable and writable:
            return _("Read and write")
        if readable:
            return _("Read only")
        if writable:
            return _("Write only")
        return _("No access")

    return describe((mode >> 6) & 7), describe((mode >> 3) & 7), describe(mode & 7)


class GetInfoDialog(Adw.Dialog):
    def __init__(self, window, item):
        super().__init__(title=_("{name} Info").format(name=item.name), content_width=420, content_height=640)
        self.window = window
        self.item = item
        page = Adw.PreferencesPage()

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header.append(build_preview(item, height=128))
        header.append(Gtk.Label(label=item.name, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                                justify=Gtk.Justification.CENTER, css_classes=["title-3"]))
        self.size_label = Gtk.Label(label=_format_size(item), css_classes=["dim-label"])
        header.append(self.size_label)
        top = Adw.PreferencesGroup()
        top.add(header)
        page.add(top)

        general = Adw.PreferencesGroup(title=_("General"))
        self._row(general, _("Kind"), item.kind)
        exact = f"{item.size:,}".replace(",", "\u202f")
        self.size_row = self._row(general, _("Size"), _("Calculating…") if item.is_dir else
                                  _("{size} ({bytes} bytes)").format(size=GLib.format_size(item.size), bytes=exact))
        parent = item.gfile.get_parent()
        if parent is not None:
            self._row(general, _("Where"), parent.get_path() or parent.get_uri())
        info = item.info
        try:
            info = item.gfile.query_info("time::*,unix::mode,owner::user,owner::group",
                                         Gio.FileQueryInfoFlags.NONE, None)
        except GLib.Error:
            pass
        for key, label in (("time::created", _("Created")), ("time::modified", _("Modified")),
                           ("time::access", _("Last opened"))):
            if info.has_attribute(key):
                self._row(general, label, _format_date(info.get_attribute_uint64(key)))
        dimensions = image_dimensions(item)
        if dimensions:
            self._row(general, _("Dimensions"), dimensions)
        page.add(general)

        tags = Adw.PreferencesGroup(title=_("Tags"))
        tag_row = Adw.ActionRow(title=", ".join(item.tags) if item.tags else _("No tags"))
        dots = TagDots(window.tagstore, 12, max_dots=8)
        dots.set_tags(item.tags)
        tag_row.add_prefix(dots)
        edit = Gtk.Button(label=_("Edit…"), valign=Gtk.Align.CENTER, css_classes=["flat"])
        edit.connect("clicked", lambda _b: self._edit_tags())
        tag_row.add_suffix(edit)
        tags.add(tag_row)
        page.add(tags)

        if item.path and not item.path.startswith(os.path.join(GLib.get_user_runtime_dir(), "gvfs")):
            comments = Adw.PreferencesGroup(title=_("Comments"))
            entry = Adw.EntryRow(title=_("Comment"), show_apply_button=True, text=self._read_comment())
            entry.connect("apply", lambda r: self._write_comment(r.get_text()))
            comments.add(entry)
            page.add(comments)

        if not item.is_dir and item.content_type:
            page.add(self._open_with_group())

        if info.has_attribute("unix::mode"):
            mode = info.get_attribute_uint32("unix::mode")
            owner, group, others = _permissions_text(mode)
            sharing = Adw.PreferencesGroup(title=GLib.markup_escape_text(_("Sharing & Permissions")))
            self._row(sharing, _("Owner ({name})").format(name=info.get_attribute_string("owner::user") or "?"), owner)
            self._row(sharing, _("Group ({name})").format(name=info.get_attribute_string("owner::group") or "?"),
                      group)
            self._row(sharing, _("Everyone"), others)
            page.add(sharing)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(page)
        self.set_child(toolbar)

        if item.is_dir:
            threading.Thread(target=self._measure, daemon=True).start()

    def _row(self, group, title, value):
        row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(value),
                            subtitle_selectable=True)
        row.add_css_class("property")
        group.add(row)
        return row

    def _measure(self):
        try:
            _ok, size, dirs, files = self.item.target_file.measure_disk_usage(
                Gio.FileMeasureFlags.APPARENT_SIZE, None, None, None)
            text = _("{size} for {n} items").format(size=GLib.format_size(size), n=dirs + files - 1)
        except GLib.Error as err:
            text = err.message
        GLib.idle_add(self._show_size, text)

    def _show_size(self, text):
        self.size_row.set_subtitle(GLib.markup_escape_text(text))
        self.size_label.set_text(text)
        return GLib.SOURCE_REMOVE

    def _read_comment(self):
        try:
            return os.getxattr(self.item.path, XATTR_COMMENT).decode("utf-8", "replace")
        except OSError:
            return ""

    def _write_comment(self, text):
        try:
            if text.strip():
                os.setxattr(self.item.path, XATTR_COMMENT, text.strip().encode("utf-8"))
            else:
                os.removexattr(self.item.path, XATTR_COMMENT)
        except OSError as err:
            if text.strip():
                self.window.toast(_("Could not save the comment: {error}").format(error=err.strerror))

    def _edit_tags(self):
        from . import dialogs

        self.close()
        dialogs.edit_tags(self.window, [self.item])

    def _open_with_group(self):
        group = Adw.PreferencesGroup(title=_("Open With"))
        apps = Gio.AppInfo.get_all_for_type(self.item.content_type)
        default = Gio.AppInfo.get_default_for_type(self.item.content_type, False)
        if not apps:
            self._row(group, _("Application"), _("None"))
            return group
        names = [app.get_display_name() for app in apps]
        combo = Adw.ComboRow(title=_("Application"), model=Gtk.StringList.new(names))
        if default is not None:
            for index, app in enumerate(apps):
                if app.get_id() == default.get_id():
                    combo.set_selected(index)
        group.add(combo)
        apply_all = None
        button = Gtk.Button(label=_("Change All…"), valign=Gtk.Align.CENTER, css_classes=["flat"])

        def change_all(*_args):
            app = apps[combo.get_selected()]
            try:
                app.set_as_default_for_type(self.item.content_type)
                self.window.toast(_("{app} will open all “{kind}” files").format(app=app.get_display_name(),
                                                                                 kind=self.item.kind))
            except GLib.Error as err:
                self.window.toast(err.message)

        if apply_all is not None:
            apply_all.connect("activated", change_all)
            group.add(apply_all)
        else:
            button.connect("clicked", change_all)
            combo.add_suffix(button)
        return group
