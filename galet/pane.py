"""A browser pane: the content of one tab."""

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk

from . import fileops, phone, quickactions
from .i18n import _, ngettext
from .model import DirectoryModel, Location, TagModel, fold
from .search import SearchModel, date_matches, kind_matches
from .info import InfoPanel
from .views import GROUPS, ColumnBrowser, DetailListView, GalleryView, GroupedIconView, IconGridView
from .widgets import FolderColorPicker, TagPicker

VIEW_MODES = ("grid", "list", "columns", "gallery")

# Shortcuts that must only work when the file view has the focus (not while
# typing in the search field or a dialog).
LOCAL_SHORTCUTS = (
    ("Delete", "win.trash"),
    ("<Shift>Delete", "win.delete-permanently"),
    ("<Control>z", "win.undo"),
    ("<Control>d", "win.duplicate"),
    ("<Control>c", "win.copy"),
    ("<Control>x", "win.cut"),
    ("<Control>v", "win.paste"),
    ("F2", "win.rename"),
    ("space", "win.quicklook"),
    ("<Control>Return", "win.open-new-tab"),
    ("<Control><Shift>c", "win.copy-path"),
)


class BrowserPane(Gtk.Box):
    __gsignals__ = {
        "location-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "status-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, window, location, view_mode, show_hidden):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.window = window
        self.tagstore = window.tagstore
        self.settings = window.settings
        self.location = None
        self.back_stack = []
        self.forward_stack = []
        self.view_mode = view_mode if view_mode in VIEW_MODES else "grid"
        self.show_hidden = show_hidden
        self.search_text = ""
        self.search_origin = None  # location to return to when a search ends
        self.search_kind = "any"
        self.search_date = "any"
        self.free_space = ""
        self.model = None
        self.filtered = None
        self.view = None

        self.filter = Gtk.CustomFilter.new(self._filter_item)
        self.stack = Gtk.Stack(vexpand=True, hexpand=True)
        self.status_page = Adw.StatusPage()
        self.stack.add_named(self.status_page, "status")
        self.info_panel = InfoPanel(window)
        body = Gtk.Box(vexpand=True)
        body.append(self.stack)
        body.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        body.append(self.info_panel)
        self._info_separator = body.get_last_child().get_prev_sibling()
        self.append(body)
        self.connect("status-changed", lambda *_a: self._update_info_panel())

        self.trash_banner = Adw.Banner(title=_("Items in the trash"), button_label=_("Empty Trash…"),
                                       action_name="win.empty-trash")
        self.prepend(self.trash_banner)

        shortcuts = Gtk.ShortcutController(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        for trigger, action in LOCAL_SHORTCUTS:
            shortcuts.add_shortcut(Gtk.Shortcut(trigger=Gtk.ShortcutTrigger.parse_string(trigger),
                                                action=Gtk.CallbackAction.new(self._guarded(action))))
        self.add_controller(shortcuts)

        # Type-ahead: typing a name selects the matching file.
        self._typed = ""
        self._typed_time = 0
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_type_ahead)
        self.add_controller(keys)

        # Views being dragged from are kept alive until the drag ends.
        self._dragging = 0
        self._retired_views = []

        self._load(location)

    # ------------------------------------------------------------ navigation

    @property
    def effective_mode(self):
        if self.view_mode == "columns" and self.location.is_virtual:
            return "list"
        return self.view_mode

    def go_to(self, location, record=True):
        if self.location is not None and location == self.location:
            return
        if record and self.location is not None:
            self.back_stack.append(self.location)
            self.forward_stack.clear()
        self._load(location)

    def go_back(self):
        if self.back_stack:
            self.forward_stack.append(self.location)
            self._load(self.back_stack.pop())

    def go_forward(self):
        if self.forward_stack:
            self.back_stack.append(self.location)
            self._load(self.forward_stack.pop())

    def go_up(self):
        parent = self.parent_dir()
        if parent is not None:
            self.go_to(Location(parent))

    def parent_dir(self):
        if self.location.is_virtual:
            return None
        return self.location.gfile.get_parent()

    def reload(self):
        self._load(self.location)

    def _view_mode_for(self, location):
        """Finder remembers the presentation of each folder."""
        if location.is_virtual:
            return self.view_mode
        stored = self.settings.get("folder_views", {}).get(location.gfile.get_uri())
        if stored in VIEW_MODES:
            return stored
        default = self.settings.get("view_mode", "grid")
        return default if default in VIEW_MODES else "grid"

    def _load(self, location):
        self._close_model()
        self.view_mode = self._view_mode_for(location)
        self.location = location
        self.search_text = ""
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        if self.effective_mode != "columns":
            if location.is_search:
                self.model = SearchModel(location.search, self.tagstore, self.show_hidden)
            elif location.is_tag:
                self.model = TagModel(location.tag, self.tagstore)
            else:
                self.model = DirectoryModel(location.gfile, self.tagstore)
            self.model.connect("loaded", self._on_loaded)
            self.model.connect("error", self._on_error)
            self.filtered = Gtk.FilterListModel(model=self.model.store, filter=self.filter)
            self.filtered.connect("items-changed", lambda *_a: self.emit("status-changed"))
        self._build_view()
        self._query_free_space()
        self.emit("location-changed")

    def _close_model(self):
        if self.model is not None:
            self.model.close()
            self.model = None
        self.filtered = None

    def _build_view(self):
        if self.view is not None:
            if self._dragging:
                self._retired_views.append(self.view)  # removing it would cancel the drag
            else:
                self.view.teardown()
                self.stack.remove(self.view)
        self.trash_banner.set_revealed(self.in_trash)
        mode = self.effective_mode
        if mode == "columns":
            self.view = ColumnBrowser(self, self.location.gfile)
            self.view.connect("directory-changed", self._on_column_directory)
        elif mode == "list":
            self.view = DetailListView(self, self.filtered)
        elif mode == "gallery":
            self.view = GalleryView(self, self.filtered)
        elif GROUPS.get(self.settings.get("group_by", "none")) is not None:
            self.view = GroupedIconView(self, self.filtered, GROUPS[self.settings.get("group_by")])
        else:
            self.view = IconGridView(self, self.filtered)
        self.view.connect("activate-item", lambda _v, item: self.open_items([item]))
        self.view.connect("selection-changed", lambda *_a: self.emit("status-changed"))
        self.stack.add_named(self.view, None)
        self._update_info_panel()
        self.stack.set_visible_child(self.view)
        GLib.idle_add(self._focus_view)

    def _focus_view(self):
        if self.view is not None:
            self.view.focus_view()
        return GLib.SOURCE_REMOVE

    def _on_column_directory(self, _view, gfile):
        self.location = Location(gfile)
        self.emit("location-changed")

    def _on_loaded(self, model):
        if model is not self.model:
            return
        if self.location.is_search and model.store.get_n_items() == 0:
            self.status_page.set_icon_name("system-search-symbolic")
            self.status_page.set_title(_("No Results"))
            self.status_page.set_description(_(
                "Galet searches file and folder names (and the text of documents with the Contents option). "
                "It cannot see what a photo shows: try another word, a folder name, or remove some filters."))
            self.stack.set_visible_child(self.status_page)
        elif self.location.is_tag and model.store.get_n_items() == 0:
            self.status_page.set_icon_name("galet-tag-symbolic")
            self.status_page.set_title(_("No Tagged Files"))
            self.status_page.set_description(
                _("Right-click a file and choose a colour to tag it."))
            self.stack.set_visible_child(self.status_page)
        else:
            self.stack.set_visible_child(self.view)
        self.emit("status-changed")

    def _on_error(self, model, message):
        if model is not self.model:
            return
        self.status_page.set_icon_name("dialog-warning-symbolic")
        self.status_page.set_title(_("Unable to Open This Folder"))
        self.status_page.set_description(message)
        self.stack.set_visible_child(self.status_page)

    def _query_free_space(self):
        self.free_space = ""
        if self.location.is_virtual:
            return
        location = self.location

        def done(gfile, result, *_args):
            try:
                info = gfile.query_filesystem_info_finish(result)
            except GLib.Error:
                return
            if self.location is location and info.has_attribute("filesystem::free"):
                free = info.get_attribute_uint64("filesystem::free")
                self.free_space = _("{size} available").format(size=GLib.format_size(free))
                self.emit("status-changed")

        location.gfile.query_filesystem_info_async("filesystem::free", GLib.PRIORITY_LOW, None, done)

    def teardown(self):
        self._close_model()
        for view in self._retired_views + ([self.view] if self.view is not None else []):
            view.teardown()
        self._retired_views = []

    # -------------------------------------------------------- drag and drop

    def drag_started(self):
        self._dragging += 1

    def drag_finished(self):
        self._dragging = max(0, self._dragging - 1)
        if not self._dragging:
            GLib.idle_add(self._drop_retired_views)

    def _drop_retired_views(self):
        for view in self._retired_views:
            view.teardown()
            self.stack.remove(view)
        self._retired_views = []
        return GLib.SOURCE_REMOVE

    def spring_open(self, folder):
        """Hovering a folder during a drag opens it (Finder's spring-loaded folders)."""
        self.go_to(Location(folder))

    # ---------------------------------------------------- keyboard helpers

    def _guarded(self, action):
        def callback(widget, *_args):
            focus = widget.get_root().get_focus() if widget.get_root() else None
            if isinstance(focus, Gtk.Editable):
                return False  # let text fields handle Delete, Ctrl+C, Ctrl+Z...
            if action == "win.quicklook" and (focus is None or not focus.is_ancestor(self)):
                return False
            return bool(widget.activate_action(action, None))
        return callback

    def _on_type_ahead(self, _controller, keyval, _keycode, state):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        codepoint = Gdk.keyval_to_unicode(keyval)
        char = chr(codepoint) if codepoint else ""
        if not char or not char.isprintable() or char.isspace():
            return False
        now = GLib.get_monotonic_time()
        if now - self._typed_time > 1_000_000:
            self._typed = ""
        self._typed += char
        self._typed_time = now
        if self.view is not None:
            self.view.select_prefix(fold(self._typed))
        return True

    # -------------------------------------------------------------- renaming

    def reveal(self, gfile, rename=False, attempts=30):
        """Select ``gfile`` once it shows up in the view (optionally rename it)."""
        if self.view is None:
            return
        if self.view.select_file(gfile):
            if rename:
                GLib.timeout_add(150, lambda: self.start_rename() and False)
            return
        if attempts:
            GLib.timeout_add(100, lambda: self.reveal(gfile, rename, attempts - 1) and False)

    def start_rename(self):
        """Rename in place: an entry appears over the file name, like Finder."""
        items = self.get_selected_items()
        if len(items) != 1:
            return False
        previous = getattr(self, "_rename_popover", None)
        if previous is not None:
            # Two grabbing popovers at once crash GTK: close the current one first.
            previous.popdown()
            self._rename_popover = None
        item = items[0]
        cell = self.view.find_cell(item)
        if cell is None or not cell.get_mapped():
            fileops.rename(self.window, item)
            return False

        host = self.window.toast_overlay  # outside the pane: our shortcuts don't fire while typing
        ok, bounds = cell.label.compute_bounds(host)
        if not ok:
            fileops.rename(self.window, item)
            return False
        entry = Gtk.Entry(text=item.name, width_chars=max(14, min(48, len(item.name) + 2)))
        popover = Gtk.Popover(child=entry, has_arrow=False, position=Gtk.PositionType.BOTTOM)
        popover.add_css_class("galet-rename")
        rect = Gdk.Rectangle()
        rect.x, rect.y = int(bounds.get_x()), int(bounds.get_y())
        rect.width, rect.height = max(1, int(bounds.get_width())), 1
        popover.set_pointing_to(rect)
        popover.set_parent(host)
        self._rename_popover = popover
        state = {"cancelled": False}

        def on_key(_c, keyval, _code, _state):
            if keyval == Gdk.KEY_Escape:
                state["cancelled"] = True
            return False

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", on_key)
        entry.add_controller(keys)
        entry.connect("activate", lambda _e: popover.popdown())

        def on_closed(_popover):
            if getattr(self, "_rename_popover", None) is popover:
                self._rename_popover = None
            new_name = entry.get_text().strip()
            if not state["cancelled"] and new_name and new_name != item.name:
                fileops.rename_to(self.window, item.gfile, new_name)
            GLib.idle_add(popover.unparent)
            GLib.idle_add(self._focus_view)

        popover.connect("closed", on_closed)
        popover.popup()
        entry.grab_focus()
        fileops.select_stem_region(entry, item.name, not item.is_dir)
        return True

    @property
    def in_trash(self):
        return (self.location is not None and not self.location.is_virtual
                and self.location.gfile.get_uri_scheme() == "trash")

    def _update_info_panel(self):
        visible = bool(self.settings.get("show_preview")) and self.effective_mode in ("grid", "list")
        self.info_panel.set_visible(visible)
        self._info_separator.set_visible(visible)
        if visible:
            self.info_panel.show_items(self.get_selected_items())

    # ---------------------------------------------------------- view options

    def set_view_mode(self, mode):
        if mode in VIEW_MODES and mode != self.view_mode:
            self.view_mode = mode
            self._load(self.location)

    def set_show_hidden(self, show):
        if show != self.show_hidden:
            self.show_hidden = show
            self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def set_search(self, text):
        text = fold(text.strip())
        if text == self.search_text:
            return
        old, self.search_text = self.search_text, text
        if old in text:
            change = Gtk.FilterChange.MORE_STRICT
        elif text in old:
            change = Gtk.FilterChange.LESS_STRICT
        else:
            change = Gtk.FilterChange.DIFFERENT
        self.filter.changed(change)

    def set_search_filters(self, kind, date):
        if (kind, date) != (self.search_kind, self.search_date):
            self.search_kind, self.search_date = kind, date
            self.filter.changed(Gtk.FilterChange.DIFFERENT)

    def _filter_item(self, item, *_args):
        if not self.show_hidden and item.hidden:
            return False
        if self.search_kind != "any" and not kind_matches(self.search_kind, item.content_type, item.is_dir, item.name):
            return False
        if self.search_date != "any" and not date_matches(self.search_date, item.mtime):
            return False
        return not self.search_text or self.search_text in item.search_key

    # ------------------------------------------------------------- selection

    def get_selected_items(self):
        return self.view.get_selected_items() if self.view is not None else []

    def current_dir(self):
        if isinstance(self.view, ColumnBrowser):
            return self.view.current_dir()
        return None if self.location.is_virtual else self.location.gfile

    def status_text(self):
        parts = []
        if self.filtered is not None:
            count = self.filtered.get_n_items()
            parts.append(ngettext("{n} item", "{n} items", count).format(n=count))
        selected = len(self.get_selected_items())
        if selected:
            parts.append(ngettext("{n} item selected", "{n} items selected", selected).format(n=selected))
        if self.free_space:
            parts.append(self.free_space)
        return " · ".join(parts)

    # --------------------------------------------------------------- actions

    def open_items(self, items, new_tab=False):
        folders = [i for i in items if i.is_dir]
        for item in items:
            if not item.is_dir:
                fileops.launch(self.window, item.target_file)
        if not folders:
            return
        if len(folders) == 1 and not new_tab and len(items) == 1:
            if self.effective_mode == "columns":
                return  # already shown in the next column
            self.go_to(Location(folders[0].target_file))
        else:
            for item in folders:
                self.window.new_tab(Location(item.target_file), select=False)

    def popup_context_menu(self, widget, x, y, on_item):
        ok, point = widget.compute_point(self, Graphene.Point().init(x, y))
        if not ok:
            return
        items = self.get_selected_items() if on_item else []
        menu = Gio.Menu()
        picker = None

        if items:
            section = Gio.Menu()
            section.append(_("Open"), "win.open")
            if any(i.is_dir for i in items):
                section.append(_("Open in New Tab"), "win.open-new-tab")
            if len(items) == 1 and not items[0].is_dir:
                section.append(_("Open With…"), "win.open-with")
            menu.append_section(None, section)

            section = Gio.Menu()
            if self.in_trash:
                section.append(_("Put Back"), "win.put-back")
                section.append(_("Delete Permanently…"), "win.delete-permanently")
                menu.append_section(None, section)
                section = Gio.Menu()
            section.append(_("Quick Look"), "win.quicklook")
            if len(items) == 1:
                section.append(_("Rename…"), "win.rename")
            if not self.in_trash:
                section.append(_("Duplicate"), "win.duplicate")
            section.append(_("Copy"), "win.copy")
            section.append(_("Cut"), "win.cut")
            section.append(_("Copy Path"), "win.copy-path")
            if not self.in_trash:
                section.append(_("Move to Trash"), "win.trash")
            menu.append_section(None, section)
            if not self.in_trash:
                section = Gio.Menu()
                section.append(_("Get Info"), "win.get-info")
                quick = quickactions.menu_entries(items)
                if quick:
                    submenu = Gio.Menu()
                    for label, action in quick:
                        submenu.append(label, action)
                    section.append_submenu(_("Quick Actions"), submenu)
                if len(items) > 1:
                    section.append(_("New Folder With Selection"), "win.new-folder-with-selection")
                devices = phone.phones().available() if all(i.path and not i.is_dir for i in items) else []
                if devices:
                    targets = Gio.Menu()
                    for path, name in devices:
                        entry = Gio.MenuItem.new(name, None)
                        entry.set_action_and_target_value("win.send-to-device", GLib.Variant("s", path))
                        targets.append_item(entry)
                    section.append_submenu(_("Send to Phone"), targets)
                menu.append_section(None, section)

            folders = [i for i in items if i.is_dir]
            if folders and not self.in_trash:
                section = Gio.Menu()
                if len(items) == 1:
                    section.append(_("Add to Sidebar"), "win.add-to-sidebar")
                color_item = Gio.MenuItem.new(None, None)
                color_item.set_attribute_value("custom", GLib.Variant("s", "folder-color"))
                section.append_item(color_item)
                menu.append_section(_("Folder Colour"), section)
            if any(i.path for i in items):
                section = Gio.Menu()
                custom = Gio.MenuItem.new(None, None)
                custom.set_attribute_value("custom", GLib.Variant("s", "tags"))
                section.append_item(custom)
                section.append(_("Tags…"), "win.edit-tags")
                if self.settings.get("ai_enabled"):
                    section.append(_("Suggest Tags (AI)"), "win.ai-tags")
                menu.append_section(None, section)
                common = set(items[0].tags)
                for item in items[1:]:
                    common &= set(item.tags)
                picker = (common, self.window.toggle_tag)
        elif self.in_trash:
            section = Gio.Menu()
            section.append(_("Empty Trash…"), "win.empty-trash")
            menu.append_section(None, section)
        else:
            section = Gio.Menu()
            section.append(_("New Folder"), "win.new-folder")
            section.append(_("Paste"), "win.paste")
            section.append(_("Undo"), "win.undo")
            menu.append_section(None, section)
            section = Gio.Menu()
            section.append(_("Open in Terminal"), "win.open-terminal")
            section.append(_("Show Hidden Files"), "win.show-hidden")
            menu.append_section(None, section)

        popover = Gtk.PopoverMenu.new_from_model(menu)
        folders = [i for i in items if i.is_dir] if items else []
        if folders and not self.in_trash:
            def on_color(color):
                popover.popdown()
                self.window.set_folder_color(folders, color)

            popover.add_child(FolderColorPicker(self.tagstore, folders[0].folder_color, on_color, self.settings),
                              "folder-color")
        if picker is not None:
            common, toggle = picker

            def on_toggle(name):
                popover.popdown()
                toggle(name)

            popover.add_child(TagPicker(self.tagstore, common, on_toggle), "tags")
        popover.set_parent(self)
        popover.set_has_arrow(False)
        popover.set_halign(Gtk.Align.START)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(point.x), int(point.y), 1, 1
        popover.set_pointing_to(rect)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()
