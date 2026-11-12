"""Big Spotlight-style search window (Ctrl+F), with Simple or AI mode."""

import os

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from . import fileops, search
from .i18n import _, ngettext
from .model import Location

MAX_ROWS = 80


def search_roots():
    """Home folder plus network drives (kDrive…) and USB disks."""
    home = GLib.get_home_dir()
    extra = []
    for mount in Gio.VolumeMonitor.get().get_mounts():
        path = mount.get_root().get_path()
        if path and path not in extra and not path.startswith(home + "/"):
            extra.append(path)
    return home, extra


class SpotlightDialog(Adw.Dialog):
    def __init__(self, window):
        super().__init__(title=_("Search"), content_width=760, content_height=560)
        self.window = window
        self.settings = window.settings
        self.model = None
        self.query = None
        self._source = 0
        self._refill_source = 0

        self.entry = Gtk.SearchEntry(hexpand=True, css_classes=["galet-spotlight-entry"])
        self.entry.connect("search-changed", lambda *_a: self._on_changed())
        self.entry.connect("activate", lambda *_a: self._on_activate())
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_entry_key)
        self.entry.add_controller(keys)

        self.simple_button = Gtk.ToggleButton(label=_("Simple"))
        ai_content = Gtk.Box(spacing=6)
        ai_content.append(Gtk.Image(icon_name="galet-ai-symbolic"))
        ai_content.append(Gtk.Label(label=_("AI")))
        self.ai_button = Gtk.ToggleButton(child=ai_content, group=self.simple_button,
                                          visible=bool(self.settings.get("ai_enabled")))
        modes = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        modes.append(self.simple_button)
        modes.append(self.ai_button)
        use_ai = self.settings.get("search_default_mode") == "ai" and self.settings.get("ai_enabled")
        (self.ai_button if use_ai else self.simple_button).set_active(True)
        self.simple_button.connect("toggled", lambda b: b.get_active() and self._mode_changed())
        self.ai_button.connect("toggled", lambda b: b.get_active() and self._mode_changed())

        top = Gtk.Box(spacing=10)
        top.append(self.entry)
        top.append(modes)

        self.status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        self.spinner = Gtk.Spinner(visible=False)
        status_row = Gtk.Box(spacing=8)
        status_row.append(self.spinner)
        status_row.append(self.status)

        self.list = Gtk.ListBox(css_classes=["navigation-sidebar", "galet-spotlight-list"])
        self.list.connect("row-activated", lambda _l, row: self._open(row.item))
        list_keys = Gtk.EventControllerKey()
        list_keys.connect("key-pressed", self._on_list_key)
        self.list.add_controller(list_keys)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.list)

        self.show_all = Gtk.Button(label=_("Show All in Galet"), css_classes=["pill"], sensitive=False)
        self.show_all.connect("clicked", lambda *_a: self._show_all())
        hint = Gtk.Label(label=_("Enter: open · Ctrl+Enter: show in folder · Esc: close"),
                         css_classes=["dim-label", "caption"], xalign=0, hexpand=True, wrap=True)
        bottom = Gtk.Box(spacing=8)
        bottom.append(hint)
        bottom.append(self.show_all)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                      margin_start=18, margin_end=18)
        for widget in (top, status_row, scroller, bottom):
            box.append(widget)
        self.set_child(box)
        self.set_focus(self.entry)
        self.connect("closed", lambda *_a: self._stop())
        self._mode_changed()

    # ---------------------------------------------------------------- modes

    @property
    def ai_mode(self):
        return self.ai_button.get_active() and self.ai_button.get_visible()

    def _mode_changed(self):
        if self.ai_mode:
            self.entry.set_placeholder_text(_("Describe what you are looking for, then press Enter"))
            self.status.set_text(_("Example: “beach photos”, “a piece of code that reads JSON”, "
                                   "“my invoices from this month”"))
        else:
            self.entry.set_placeholder_text(_("Search files and folders by name"))
            self.status.set_text("")
            self._on_changed()
        self.entry.grab_focus()

    def _on_changed(self):
        if self.ai_mode:
            return
        if self._source:
            GLib.source_remove(self._source)
        self._source = GLib.timeout_add(250, self._simple_search)

    def _simple_search(self):
        self._source = 0
        text = self.entry.get_text().strip()
        if len(text) < 2:
            self._stop()
            self._clear()
            self.status.set_text("")
            return GLib.SOURCE_REMOVE
        root, extra = search_roots()
        self._run(search.SearchQuery(text, root, extra_roots=extra))
        return GLib.SOURCE_REMOVE

    def _on_activate(self):
        if self.ai_mode:
            self._ask_ai()
            return
        row = self.list.get_row_at_index(0)
        if row is not None:
            self._open(row.item)

    def _ask_ai(self):
        from . import ai
        from .logs import log

        request = self.entry.get_text().strip()
        if not request:
            return
        self._busy(True, _("Asking the AI…"))

        def done(result, error):
            self._busy(False)
            if error:
                log.warning("AI search failed (%s): %s", ai.provider(self.settings), error)
                self.status.set_text(_("The AI is not available: {error}").format(error=error))
                return
            kinds, dates = dict(search.KINDS), dict(search.DATES)
            parts = [_(kinds[result["kind"]]), _(dates[result["date"]])]
            if result["text"]:
                parts.append(_("“{text}”").format(text=", ".join([result["text"], *result["keywords"][:4]])))
            if result["content"]:
                parts.append(_("inside documents"))
            self._understood = _("AI understood: {summary}").format(summary=" · ".join(parts))
            root, extra = search_roots()
            self._run(search.SearchQuery(result["text"], root, result["kind"], result["date"],
                                         content=result["content"], keywords=result["keywords"], extra_roots=extra))

        self._understood = ""
        ai.run(lambda: ai.parse_search(self.settings, request), done)

    # -------------------------------------------------------------- results

    def _run(self, query):
        self._stop()
        self._clear()
        self.query = query
        self.model = search.SearchModel(query, self.window.tagstore)
        self.model.store.connect("items-changed", lambda *_a: self._queue_refill())
        self.model.connect("loaded", lambda *_a: self._finished())
        self._busy(True, getattr(self, "_understood", "") or _("Searching…"))
        self.show_all.set_sensitive(True)

    def _stop(self):
        if self.model is not None:
            self.model.close()
            self.model = None

    def _busy(self, busy, text=None):
        self.spinner.set_visible(busy)
        self.spinner.set_spinning(busy)
        if text is not None:
            self.status.set_text(text)

    def _clear(self):
        self.list.remove_all()

    def _queue_refill(self):
        if not self._refill_source:
            self._refill_source = GLib.timeout_add(120, self._refill)

    def _refill(self):
        self._refill_source = 0
        if self.model is None:
            return GLib.SOURCE_REMOVE
        shown = len(list(self._rows()))
        store = self.model.store
        for index in range(shown, min(store.get_n_items(), MAX_ROWS)):
            self.list.append(self._row(store.get_item(index)))
        return GLib.SOURCE_REMOVE

    def _rows(self):
        row = self.list.get_first_child()
        while row is not None:
            yield row
            row = row.get_next_sibling()

    def _finished(self):
        self._refill()
        count = self.model.store.get_n_items() if self.model else 0
        prefix = (getattr(self, "_understood", "") + " — ") if getattr(self, "_understood", "") else ""
        if count:
            self._busy(False, prefix + ngettext("{n} result", "{n} results", count).format(n=count))
        else:
            self._busy(False, prefix + _("No Results"))

    def _row(self, item):
        box = Gtk.Box(spacing=12, margin_top=4, margin_bottom=4)
        image = Gtk.Image(pixel_size=32)
        if item.thumbnail:
            image.set_from_file(item.thumbnail)
        elif item.icon is not None:
            image.set_from_gicon(item.icon)
        box.append(image)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        texts.append(Gtk.Label(label=item.name, xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE,
                               css_classes=["heading"]))
        parent = os.path.dirname(item.path or "")
        home = GLib.get_home_dir()
        if parent == home or parent.startswith(home + "/"):
            parent = "~" + parent[len(home):]
        texts.append(Gtk.Label(label=parent, xalign=0, ellipsize=Pango.EllipsizeMode.START,
                               css_classes=["dim-label", "caption"]))
        box.append(texts)
        box.append(Gtk.Label(label=item.kind, css_classes=["dim-label", "caption"]))
        row = Gtk.ListBoxRow(child=box)
        row.item = item
        return row

    # -------------------------------------------------------------- actions

    def _open(self, item):
        if item.is_dir:
            self.window.navigate(Location(item.target_file))
        else:
            fileops.launch(self.window, item.target_file)
        self.close()

    def _reveal(self, item):
        parent = item.gfile.get_parent()
        if parent is not None:
            self.window.navigate(Location(parent))
            GLib.timeout_add(300, lambda: self.window.current_pane.reveal(item.gfile) and False)
        self.close()

    def _show_all(self):
        if self.query is not None:
            self.window.current_pane.go_to(Location(search=self.query))
        self.close()

    def _on_entry_key(self, _controller, keyval, _code, _state):
        if keyval == Gdk.KEY_Down:
            row = self.list.get_row_at_index(0)
            if row is not None:
                row.grab_focus()
                return True
        return False

    def _on_list_key(self, _controller, keyval, _code, state):
        row = self.list.get_focus_child()
        if row is None or not hasattr(row, "item"):
            return False
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and state & Gdk.ModifierType.CONTROL_MASK:
            self._reveal(row.item)
            return True
        return False
