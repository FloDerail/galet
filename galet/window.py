"""Main window: sidebar, tabs, toolbar, path bar."""

import os

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import dialogs, dnd, fileops, quickactions, search, servers
from .i18n import _, ngettext
from .model import Location, start_location
from .operations import OperationsButton
from .pane import BrowserPane
from .sidebar import Sidebar
from .widgets import PathBar

SELECTION_ACTIONS = ("open", "open-new-tab", "quicklook", "copy", "cut", "copy-path", "trash", "edit-tags",
                     "duplicate", "delete-permanently", "get-info", "quick-action")


class GaletWindow(Adw.ApplicationWindow):
    def __init__(self, app, location=None):
        super().__init__(application=app, title="Galet", width_request=360, height_request=320)
        self.app = app
        self._resetting_search = False
        self.tagstore = app.tagstore
        self.settings = app.settings
        width, height = self.settings.get("window_size", [1100, 700])
        self.set_default_size(width, height)
        self._build_ui()
        self._setup_actions()
        self.connect("close-request", self._on_close_request)
        self._settings_handler = self.settings.connect("changed", self._on_setting_changed)
        self.new_tab(location or start_location(self.settings.get("new_window_location")))

    # -------------------------------------------------------------------- UI

    def _build_ui(self):
        # Sidebar
        self.sidebar = Sidebar(self)
        sidebar_view = Adw.ToolbarView()
        sidebar_view.add_top_bar(Adw.HeaderBar(show_title=False))
        sidebar_view.set_content(self.sidebar)

        # Header bar
        header = Adw.HeaderBar()
        self.sidebar_button = Gtk.ToggleButton(icon_name="sidebar-show-symbolic", visible=False,
                                               tooltip_text=_("Show Sidebar"))
        header.pack_start(self.sidebar_button)
        navigation = Gtk.Box(css_classes=["linked"])
        navigation.append(Gtk.Button(icon_name="go-previous-symbolic", action_name="win.back",
                                     tooltip_text=_("Back")))
        navigation.append(Gtk.Button(icon_name="go-next-symbolic", action_name="win.forward",
                                     tooltip_text=_("Forward")))
        header.pack_start(navigation)
        self.window_title = Adw.WindowTitle()
        header.set_title_widget(self.window_title)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append(_("New Window"), "app.new-window")
        section.append(_("New Tab"), "win.new-tab")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("Show Preview"), "win.show-preview")
        group_menu = Gio.Menu()
        for key, label in (("none", _("None")), ("kind", _("Kind")), ("date", _("Date Modified")),
                           ("tags", _("Tags"))):
            group_menu.append(label, f"win.group-by::{key}")
        section.append_submenu(_("Group By (List View)"), group_menu)
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("Go to Location…"), "win.go-to")
        section.append(_("Connect to Server…"), "win.connect-server")
        section.append(_("Show Hidden Files"), "win.show-hidden")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append(_("Settings"), "app.preferences")
        section.append(_("About Galet"), "app.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, primary=True,
                                       tooltip_text=_("Main Menu")))

        search_button = Gtk.ToggleButton(icon_name="system-search-symbolic", tooltip_text=_("Search"))
        header.pack_end(search_button)
        self.operations_button = OperationsButton()
        header.pack_end(self.operations_button)

        modes = Gtk.Box(css_classes=["linked"])
        for mode, icon, tooltip in (("grid", "view-grid-symbolic", _("Icons")),
                                    ("list", "view-list-symbolic", _("List")),
                                    ("columns", "galet-view-columns-symbolic", _("Columns")),
                                    ("gallery", "view-paged-symbolic", _("Gallery"))):
            button = Gtk.ToggleButton(icon_name=icon, tooltip_text=tooltip)
            button.set_detailed_action_name(f"win.view-mode::{mode}")
            modes.append(button)
        header.pack_end(modes)

        # Search bar
        self.search_entry = Gtk.SearchEntry(placeholder_text=_("Search"), hexpand=True)
        self.search_entry.connect("search-changed", lambda *_a: self._apply_search())
        self.search_entry.connect("stop-search", lambda *_a: self.search_bar.set_search_mode(False))
        search_row = Gtk.Box(spacing=6)
        search_row.append(self.search_entry)
        scopes = Gtk.Box(css_classes=["linked"])
        self.scope_buttons = {}
        first = None
        for key, label, tooltip in (("folder", _("This Folder"), _("Filter the current folder")),
                                    ("subfolders", _("Subfolders"), _("Search this folder and all its subfolders")),
                                    ("home", _("Everywhere"), _("Search your whole home folder"))):
            button = Gtk.ToggleButton(label=label, tooltip_text=tooltip, group=first)
            first = first or button
            button.connect("toggled", lambda b: b.get_active() and self._apply_search())
            scopes.append(button)
            self.scope_buttons[key] = button
        self.scope_buttons["folder"].set_active(True)
        search_row.append(scopes)
        self.kind_dropdown = Gtk.DropDown.new_from_strings([_(label) for _k, label in search.KINDS])
        self.kind_dropdown.connect("notify::selected", lambda *_a: self._apply_search())
        self.date_dropdown = Gtk.DropDown.new_from_strings([_(label) for _k, label in search.DATES])
        self.date_dropdown.connect("notify::selected", lambda *_a: self._apply_search())
        search_row.append(self.kind_dropdown)
        search_row.append(self.date_dropdown)
        self.save_search_button = Gtk.Button(icon_name="document-save-symbolic", sensitive=False,
                                             tooltip_text=_("Save as Smart Folder"), css_classes=["flat"])
        self.save_search_button.connect("clicked", lambda *_a: self._save_search())
        search_row.append(self.save_search_button)
        self.search_bar = Gtk.SearchBar(child=Adw.Clamp(child=search_row, maximum_size=980))
        self.search_bar.connect_entry(self.search_entry)
        search_button.bind_property("active", self.search_bar, "search-mode-enabled",
                                    GObject.BindingFlags.BIDIRECTIONAL)
        self.search_bar.connect("notify::search-mode-enabled", self._on_search_mode)

        # Tabs
        self.tab_view = Adw.TabView()
        self.tab_view.connect("notify::selected-page", lambda *_a: self._sync_chrome())
        self.tab_view.connect("close-page", self._on_close_page)
        self.tab_view.connect("notify::n-pages", self._on_n_pages)
        self.tab_bar = Adw.TabBar(view=self.tab_view, autohide=True)
        self.tab_bar.setup_extra_drop_target(dnd.ACTIONS, [Gdk.FileList])
        self.tab_bar.connect("extra-drag-drop", self._on_tab_drop)
        self.tab_bar.set_end_action_widget(Gtk.Button(icon_name="tab-new-symbolic", action_name="win.new-tab",
                                                      css_classes=["flat"], tooltip_text=_("New Tab")))

        # Bottom bar: path + status
        self.path_bar = PathBar(self.navigate, self.tagstore, self.drop_files)
        self.status_label = Gtk.Label(css_classes=["dim-label", "caption"], xalign=1, margin_end=6)
        bottom = Gtk.Box(spacing=8, css_classes=["galet-bottombar"],
                         visible=self.settings.get("show_bottom_bar"))
        self.bottom_bar = bottom
        bottom.append(self.path_bar)
        bottom.append(self.status_label)

        self.toast_overlay = Adw.ToastOverlay(child=self.tab_view)
        content = Adw.ToolbarView()
        content.add_top_bar(header)
        content.add_top_bar(self.tab_bar)
        content.add_top_bar(self.search_bar)
        content.add_bottom_bar(bottom)
        content.set_content(self.toast_overlay)

        self.split = Adw.OverlaySplitView(sidebar=sidebar_view, content=content,
                                          min_sidebar_width=190, max_sidebar_width=260)
        self.split.bind_property("show-sidebar", self.sidebar_button, "active",
                                 GObject.BindingFlags.BIDIRECTIONAL | GObject.BindingFlags.SYNC_CREATE)
        self.set_content(self.split)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        breakpoint.add_setter(self.split, "collapsed", GObject.Value(GObject.TYPE_BOOLEAN, True))
        breakpoint.add_setter(self.split, "show-sidebar", GObject.Value(GObject.TYPE_BOOLEAN, False))
        breakpoint.add_setter(self.sidebar_button, "visible", GObject.Value(GObject.TYPE_BOOLEAN, True))
        self.add_breakpoint(breakpoint)

    # --------------------------------------------------------------- actions

    def _setup_actions(self):
        simple = {
            "back": lambda: self.current_pane.go_back(),
            "forward": lambda: self.current_pane.go_forward(),
            "up": lambda: self.current_pane.go_up(),
            "reload": lambda: self.current_pane.reload(),
            "new-tab": lambda: self.new_tab(self.current_pane.location if self.current_pane else None),
            "close-tab": self._close_current_tab,
            "search": lambda: self.search_bar.set_search_mode(not self.search_bar.get_search_mode()),
            "go-to": self._go_to_dialog,
            "open": lambda: self.current_pane.open_items(self.selection),
            "open-new-tab": lambda: self.current_pane.open_items(self.selection, new_tab=True),
            "open-with": lambda: fileops.launch(self, self.selection[0].target_file, always_ask=True),
            "quicklook": lambda: fileops.quicklook(self, self.selection[0]),
            "rename": lambda: self.current_pane.start_rename(),
            "undo": lambda: fileops.undo_last(self),
            "duplicate": lambda: fileops.duplicate(self, self.selection),
            "put-back": lambda: fileops.put_back(self, self.selection),
            "empty-trash": lambda: fileops.empty_trash(self),
            "delete-permanently": lambda: fileops.delete_permanently(self, [i.gfile for i in self.selection]),
            "new-folder-with-selection": lambda: fileops.new_folder_with_selection(
                self, self.current_pane.current_dir(), self.selection,
                lambda folder: self.current_pane.reveal(folder, rename=True)),
            "trash": lambda: fileops.trash(self, self.selection),
            "copy": lambda: fileops.copy_to_clipboard(self, self.selection, cut=False),
            "cut": lambda: fileops.copy_to_clipboard(self, self.selection, cut=True),
            "copy-path": lambda: fileops.copy_paths(self, self.selection),
            "paste": lambda: fileops.paste(self, self.current_pane.current_dir()),
            "new-folder": lambda: fileops.new_folder(self, self.current_pane.current_dir(),
                                                      lambda folder: self.current_pane.reveal(folder, rename=True)),
            "open-terminal": lambda: fileops.open_terminal(self, self.current_pane.current_dir()),
            "edit-tags": lambda: dialogs.edit_tags(self, self.selection),
            "connect-server": lambda: servers.ConnectDialog(self).present(self),
            "get-info": self._get_info,
        }
        for name, callback in simple.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, cb=callback: cb())
            self.add_action(action)

        for name, callback in (("toggle-tag", self.toggle_tag),
                               ("delete-tag", lambda tag: dialogs.delete_tag(self, tag)),
                               ("disconnect", self._disconnect_uri),
                               ("remove-server", lambda uri: servers.remove_server(self.settings, uri)),
                               ("quick-action", lambda name: quickactions.run(self, name, self.selection)),
                               ("remove-smart-folder", lambda name: search.remove_smart_folder(self.settings, name)),
                               ("send-to-device", self._send_to_device)):
            action = Gio.SimpleAction.new(name, GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, param, cb=callback: cb(param.get_string()))
            self.add_action(action)

        self.view_mode_action = Gio.SimpleAction.new_stateful(
            "view-mode", GLib.VariantType.new("s"), GLib.Variant("s", self.settings.get("view_mode", "grid")))
        self.view_mode_action.connect("change-state", self._on_view_mode)
        self.add_action(self.view_mode_action)

        self.preview_action = Gio.SimpleAction.new_stateful(
            "show-preview", None, GLib.Variant("b", bool(self.settings.get("show_preview", False))))
        self.preview_action.connect("change-state", self._on_toggle_setting, "show_preview")
        self.add_action(self.preview_action)
        self.group_action = Gio.SimpleAction.new_stateful(
            "group-by", GLib.VariantType.new("s"), GLib.Variant("s", self.settings.get("group_by", "none")))
        self.group_action.connect("change-state", self._on_group_by)
        self.add_action(self.group_action)

        self.hidden_action = Gio.SimpleAction.new_stateful(
            "show-hidden", None, GLib.Variant("b", self.settings.get("show_hidden", False)))
        self.hidden_action.connect("change-state", self._on_show_hidden)
        self.add_action(self.hidden_action)

    def _enable(self, name, enabled):
        action = self.lookup_action(name)
        if action is not None:
            action.set_enabled(bool(enabled))

    def _update_actions(self):
        pane = self.current_pane
        if pane is None:
            return
        selection = self.selection
        for name in SELECTION_ACTIONS:
            self._enable(name, selection)
        self._enable("rename", len(selection) == 1)
        self._enable("open-with", len(selection) == 1 and not selection[0].is_dir)
        self._enable("edit-tags", any(i.path for i in selection))
        self._enable("back", pane.back_stack)
        self._enable("forward", pane.forward_stack)
        self._enable("up", pane.parent_dir() is not None)
        directory = pane.current_dir()
        self._enable("new-folder", directory is not None)
        self._enable("paste", directory is not None)
        self._enable("open-terminal", directory is not None and directory.get_path())
        self._enable("new-folder-with-selection", directory is not None and selection)
        in_trash = pane.in_trash
        self._enable("put-back", in_trash and selection)
        self._enable("duplicate", selection and not in_trash)

    def _on_toggle_setting(self, action, value, key):
        action.set_state(value)
        self.settings.set(key, value.get_boolean())

    def _on_group_by(self, action, value):
        action.set_state(value)
        self.settings.set("group_by", value.get_string())

    def _send_to_device(self, path):
        from . import phone

        files = [i for i in self.selection if i.path and not i.is_dir]
        if files and phone.phones().send(path, [i.gfile.get_uri() for i in files]):
            name = phone.phones().devices[path]["name"]
            self.toast(ngettext("Sending {n} file to {device}…", "Sending {n} files to {device}…",
                                len(files)).format(n=len(files), device=name))

    def _get_info(self):
        from .info import GetInfoDialog

        for item in self.selection[:3]:
            GetInfoDialog(self, item).present(self)

    def _on_view_mode(self, action, value):
        action.set_state(value)
        mode = value.get_string()
        self.settings.set("view_mode", mode)
        if self.current_pane is not None:
            self.current_pane.set_view_mode(mode)
            self._sync_chrome()

    def _on_show_hidden(self, action, value):
        action.set_state(value)
        self.settings.set("show_hidden", value.get_boolean())
        for pane in self.panes:
            pane.set_show_hidden(value.get_boolean())

    def _on_setting_changed(self, _settings, key):
        if key == "show_preview":
            for pane in self.panes:
                pane._update_info_panel()
            value = GLib.Variant("b", bool(self.settings.get(key)))
            if self.preview_action.get_state() != value:
                self.preview_action.set_state(value)
        elif key in ("icon_size", "folders_first", "show_extensions", "group_by"):
            for pane in self.panes:
                pane.reload()
        elif key == "show_bottom_bar":
            self.bottom_bar.set_visible(self.settings.get(key))
        elif key == "show_hidden":
            value = GLib.Variant("b", bool(self.settings.get(key)))
            if self.hidden_action.get_state() != value:
                self.hidden_action.change_state(value)

    # ------------------------------------------------------------------ tabs

    @property
    def current_pane(self):
        page = self.tab_view.get_selected_page()
        return page.get_child() if page is not None else None

    @property
    def panes(self):
        return [self.tab_view.get_nth_page(i).get_child() for i in range(self.tab_view.get_n_pages())]

    @property
    def selection(self):
        pane = self.current_pane
        return pane.get_selected_items() if pane is not None else []

    def new_tab(self, location=None, select=True):
        pane = BrowserPane(self, location or Location.home(), self.view_mode_action.get_state().get_string(),
                           self.hidden_action.get_state().get_boolean())
        page = self.tab_view.append(pane)
        page.set_title(pane.location.title)
        page.set_icon(Gio.ThemedIcon.new("folder-symbolic"))
        pane.connect("location-changed", self._on_pane_location, page)
        pane.connect("status-changed", self._on_pane_status)
        if select:
            self.tab_view.set_selected_page(page)
        return pane

    def navigate(self, location):
        pane = self.current_pane
        if pane is None:
            return
        if location.is_virtual:
            pane.go_to(location)
        else:
            servers.ensure_mounted(self, location.gfile, lambda: pane.go_to(location))

    def open_server(self, gfile):
        self.navigate(Location(gfile))

    def _disconnect_uri(self, uri):
        mount = servers.find_mount(Gio.File.new_for_uri(uri))
        if mount is not None:
            self.unmount(mount)

    def unmount(self, mount):
        root = mount.get_root()
        for pane in self.panes:
            location = pane.location
            if not location.is_virtual and (location.gfile.equal(root) or location.gfile.has_prefix(root)):
                pane.go_to(Location.home())
        servers.unmount(self, mount)

    # ------------------------------------------------------- drag and drop

    def drop_files(self, files, destination, action):
        """Copy or move dropped files into ``destination`` (a Gio.File)."""
        move = action == Gdk.DragAction.MOVE
        files = [f for f in files if not f.equal(destination)]
        if move:
            files = [f for f in files if f.get_parent() is None or not f.get_parent().equal(destination)]
        if not files:
            return
        uris = [f.get_uri() for f in files]
        servers.ensure_mounted(self, destination, lambda: fileops.transfer(self, uris, destination, move))

    def drop_on_tag(self, files, tag):
        paths = [f.get_path() for f in files if f.get_path()]
        try:
            for path in paths:
                tags = self.tagstore.read(path)
                if tag not in tags:
                    self.tagstore.write(path, tags + [tag])
        except OSError as err:
            self.toast(_("Could not change tags: {error}").format(error=err.strerror or err))
            return
        self.toast(_("Tag “{tag}” added").format(tag=tag))

    def _on_tab_drop(self, _bar, page, value, *_args):
        destination = page.get_child().current_dir()
        files = list(value.get_files()) if value is not None else []
        if destination is None or not files:
            return False
        state = Gdk.ModifierType(0)
        self.drop_files(files, destination, dnd.choose_action(state, files, destination))
        return True

    def _close_current_tab(self):
        page = self.tab_view.get_selected_page()
        if page is not None:
            self.tab_view.close_page(page)

    def _on_close_page(self, _view, page):
        page.get_child().teardown()
        return False  # let AdwTabView finish closing

    def _on_n_pages(self, *_args):
        if self.tab_view.get_n_pages() == 0:
            self.close()

    def _on_pane_location(self, pane, page):
        page.set_title(pane.location.title)
        icon = ("galet-tag-symbolic" if pane.location.is_tag else
                "system-search-symbolic" if pane.location.is_search else "folder-symbolic")
        page.set_icon(Gio.ThemedIcon.new(icon))
        if pane is self.current_pane:
            self._sync_chrome()

    def _on_pane_status(self, pane):
        if pane is self.current_pane:
            self.status_label.set_text(pane.status_text())
            self._update_actions()

    def _sync_chrome(self):
        pane = self.current_pane
        if pane is None:
            return
        location = pane.location
        title = location.title
        self.window_title.set_title(title)
        self.set_title(title)
        self.path_bar.set_location(location)
        self.sidebar.select_location(location)
        self.view_mode_action.set_state(GLib.Variant("s", pane.view_mode))
        if not location.is_search and pane.search_origin is not None:
            pane.search_origin = None  # the user navigated away from the results
        if (self.search_entry.get_text() and not pane.search_text and not location.is_search
                and pane.search_origin is None):
            self._reset_search_controls()
        self.status_label.set_text(pane.status_text())
        self._update_actions()

    # ---------------------------------------------------------------- search

    def _search_scope(self):
        for key, button in self.scope_buttons.items():
            if button.get_active():
                return key
        return "folder"

    def _apply_search(self):
        if getattr(self, "tab_view", None) is None or self._resetting_search:
            return  # still building the window
        pane = self.current_pane
        if pane is None:
            return
        text = self.search_entry.get_text()
        kind = search.KINDS[self.kind_dropdown.get_selected()][0]
        date = search.DATES[self.date_dropdown.get_selected()][0]
        scope = self._search_scope()
        origin = pane.search_origin or pane.location
        if scope == "folder" or (not text.strip() and kind == "any" and date == "any"):
            if pane.search_origin is not None:
                pane.search_origin = None
                pane.go_to(origin, record=False)
            pane.set_search(text)
            pane.set_search_filters(kind, date)
            self.save_search_button.set_sensitive(False)
            return
        root = GLib.get_home_dir()
        if scope == "subfolders" and not origin.is_virtual and origin.gfile.get_path():
            root = origin.gfile.get_path()
        query = search.SearchQuery(text, root, kind, date)
        pane.search_origin = origin
        pane.go_to(Location(search=query), record=False)
        pane.set_search_filters(kind, date)
        self.save_search_button.set_sensitive(True)

    def _reset_search_controls(self):
        self._resetting_search = True
        self.search_entry.set_text("")
        self.kind_dropdown.set_selected(0)
        self.date_dropdown.set_selected(0)
        self.scope_buttons["folder"].set_active(True)
        self._resetting_search = False
        self.save_search_button.set_sensitive(False)

    def _save_search(self):
        pane = self.current_pane
        if pane is None or not pane.location.is_search:
            return
        query = pane.location.search
        fileops.ask_text(self, _("Save Smart Folder"), query.text or _("Smart Folder"), _("Save"),
                         lambda name: (search.save_smart_folder(self.settings, name, query),
                                       self.toast(_("Smart folder “{name}” saved").format(name=name))))

    def _on_search_mode(self, bar, _pspec):
        if not bar.get_search_mode():
            pane = self.current_pane
            self._reset_search_controls()
            if pane is not None:
                if pane.search_origin is not None:
                    origin, pane.search_origin = pane.search_origin, None
                    pane.go_to(origin, record=False)
                pane.set_search("")
                pane.set_search_filters("any", "any")
                pane.view.focus_view()

    # ----------------------------------------------------------------- misc

    def toast(self, message, undo=False):
        toast = Adw.Toast(title=GLib.markup_escape_text(message), timeout=4 if undo else 3)
        if undo:
            toast.set_button_label(_("Undo"))
            toast.set_action_name("win.undo")
        self.toast_overlay.add_toast(toast)

    def start_operation(self, operation):
        self.operations_button.add(operation)
        return operation

    def toggle_tag(self, name):
        paths = [i.path for i in self.selection if i.path]
        try:
            self.tagstore.toggle(paths, name)
        except OSError as err:
            self.toast(_("Could not change tags: {error}").format(error=err.strerror or err))

    def _go_to_dialog(self):
        directory = self.current_pane.current_dir()
        initial = (directory.get_path() or directory.get_uri()) if directory else GLib.get_home_dir()

        def go(text):
            text = os.path.expanduser(text)
            gfile = Gio.File.new_for_commandline_arg(text)
            if gfile.query_file_type(Gio.FileQueryInfoFlags.NONE, None) == Gio.FileType.DIRECTORY:
                self.navigate(Location(gfile))
            else:
                self.toast(_("No folder at “{path}”").format(path=text))

        fileops.ask_text(self, _("Go to Location"), initial, _("Go"), go)

    def _on_close_request(self, *_args):
        if not self.is_maximized():
            self.settings.set("window_size", [self.get_width(), self.get_height()])
        for pane in self.panes:
            pane.teardown()
        self.sidebar.teardown()
        self.settings.disconnect(self._settings_handler)
        return False
