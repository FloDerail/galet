"""Settings window, organised like Finder's: General, Sidebar, Tags, Advanced."""

from gi.repository import Adw, Gtk

from . import servers
from .i18n import _
from .tags import PALETTE
from .widgets import TagDots

START_CHOICES = (("home", "Home"), ("recent", "Recent"), ("desktop", "Desktop"),
                 ("documents", "Documents"), ("downloads", "Downloads"))
VIEW_CHOICES = (("grid", "Icons"), ("list", "List"), ("columns", "Columns"), ("gallery", "Gallery"))
SIDEBAR_CHOICES = (
    ("recent", "Recent"), ("home", "Home"), ("desktop", "Desktop"), ("documents", "Documents"),
    ("downloads", "Downloads"), ("pictures", "Pictures"), ("music", "Music"), ("videos", "Videos"),
    ("bookmarks", "Bookmarks"), ("computer", "Computer"), ("mounts", "External Drives"),
    ("network", "Network"), ("servers", "Servers"), ("trash", "Trash"), ("tags", "Tags"),
)


def _switch(settings, key, title, subtitle=None):
    row = Adw.SwitchRow(title=title, active=bool(settings.get(key)))
    if subtitle:
        row.set_subtitle(subtitle)
    row.connect("notify::active", lambda r, _p: settings.set(key, r.get_active()))
    return row


def _combo(settings, key, title, choices):
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new([_(label) for _k, label in choices]))
    keys = [k for k, _label in choices]
    current = settings.get(key)
    if current in keys:
        row.set_selected(keys.index(current))
    row.connect("notify::selected", lambda r, _p: settings.set(key, keys[r.get_selected()]))
    return row


def _color_dropdown(color):
    dropdown = Gtk.DropDown.new_from_strings([_("No Color")] + [_(name) for name, _c in PALETTE])
    dropdown.set_valign(Gtk.Align.CENTER)
    colors = [None] + [c for _n, c in PALETTE]
    dropdown.set_selected(colors.index(color) if color in colors else 0)
    return dropdown, colors


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, app):
        super().__init__(title=_("Settings"), search_enabled=False)
        self.settings = app.settings
        self.tagstore = app.tagstore
        self.add(self._general_page())
        self.add(self._sidebar_page())
        self.add(self._tags_page())
        self.add(self._servers_page())
        self.add(self._advanced_page())
        self._tags_handler = self.tagstore.connect("tags-changed", lambda *_a: self._fill_tags())
        self._settings_handler = self.settings.connect(
            "changed", lambda _s, key: self._fill_servers() if key == "servers" else None)
        self.connect("closed", self._on_closed)
        self.app = app

    def _on_closed(self, *_args):
        self.tagstore.disconnect(self._tags_handler)
        self.settings.disconnect(self._settings_handler)

    # ---------------------------------------------------------------- general

    def _general_page(self):
        page = Adw.PreferencesPage(title=_("General"), icon_name="preferences-system-symbolic")

        windows = Adw.PreferencesGroup(title=_("Windows"))
        windows.add(_combo(self.settings, "new_window_location", _("New windows show"), START_CHOICES))
        windows.add(_switch(self.settings, "open_in_tabs", _("Open folders in tabs instead of new windows"),
                            _("When another application asks to open a folder")))
        page.add(windows)

        view = Adw.PreferencesGroup(title=_("View"))
        view.add(_combo(self.settings, "view_mode", _("Default view"), VIEW_CHOICES))

        size_row = Adw.ActionRow(title=_("Icon size"))
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 32, 128, 16)
        scale.set_value(self.settings.get("icon_size"))
        scale.set_size_request(200, -1)
        scale.set_valign(Gtk.Align.CENTER)
        scale.set_draw_value(False)
        for mark in (32, 64, 96, 128):
            scale.add_mark(mark, Gtk.PositionType.BOTTOM, None)
        scale.connect("value-changed", lambda s: self.settings.set("icon_size", int(round(s.get_value() / 16) * 16)))
        size_row.add_suffix(scale)
        view.add(size_row)
        view.add(_switch(self.settings, "show_bottom_bar", _("Show path and status bar")))
        page.add(view)
        return page

    # ---------------------------------------------------------------- sidebar

    def _sidebar_page(self):
        page = Adw.PreferencesPage(title=_("Sidebar"), icon_name="sidebar-show-symbolic")
        group = Adw.PreferencesGroup(title=_("Show these items in the sidebar"))
        for key, label in SIDEBAR_CHOICES:
            row = Adw.SwitchRow(title=_(label), active=self.settings.sidebar_shows(key))
            row.connect("notify::active", lambda r, _p, k=key: self.settings.set_sidebar(k, r.get_active()))
            group.add(row)
        page.add(group)
        return page

    # ------------------------------------------------------------------- tags

    def _tags_page(self):
        self.tags_page = Adw.PreferencesPage(title=_("Tags"), icon_name="galet-tag-symbolic")
        self.tags_group = None

        new_group = Adw.PreferencesGroup(title=_("New Tag"))
        entry = Adw.EntryRow(title=_("Name"), show_apply_button=True)
        dropdown, colors = _color_dropdown("#007aff")
        entry.add_suffix(dropdown)

        def create(_row):
            if entry.get_text().strip():
                self.tagstore.add_tag(entry.get_text(), colors[dropdown.get_selected()])
                entry.set_text("")

        entry.connect("apply", create)
        entry.connect("entry-activated", create)
        new_group.add(entry)
        self.tags_page.add(new_group)
        self._fill_tags()
        return self.tags_page

    def _fill_tags(self):
        if self.tags_group is not None:
            self.tags_page.remove(self.tags_group)
        self.tags_group = Adw.PreferencesGroup(
            title=_("Your Tags"),
            description=_("Rename a tag by editing its name. The switch shows it in the sidebar."))
        for tag in self.tagstore.tags:
            self.tags_group.add(self._tag_row(tag))
        self.tags_page.add(self.tags_group)

    def _tag_row(self, tag):
        name = tag["name"]
        row = Adw.EntryRow(title=_("Tag"), text=name, show_apply_button=True)
        dots = TagDots(self.tagstore, 14)
        dots.set_colors([tag["color"]])
        row.add_prefix(dots)

        dropdown, colors = _color_dropdown(tag["color"])
        dropdown.connect("notify::selected",
                         lambda d, _p: self.tagstore.set_color(name, colors[d.get_selected()]))
        row.add_suffix(dropdown)

        visible = Gtk.Switch(active=tag.get("visible", True), valign=Gtk.Align.CENTER,
                             tooltip_text=_("Show in sidebar"))
        visible.connect("notify::active", lambda s, _p: self.tagstore.set_visible(name, s.get_active()))
        row.add_suffix(visible)

        delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                            css_classes=["flat"], tooltip_text=_("Delete Tag…"))
        delete.connect("clicked", lambda _b: self._confirm_delete(name))
        row.add_suffix(delete)

        def rename(r):
            if not self.tagstore.rename_tag(name, r.get_text()):
                r.set_text(name)
                self.add_toast(Adw.Toast(title=_("This name is already used.")))

        row.connect("apply", rename)
        return row

    def _confirm_delete(self, name):
        dialog = Adw.AlertDialog(heading=_("Delete Tag “{name}”?").format(name=name),
                                 body=_("The tag will be removed from all files."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: self.tagstore.remove_tag(name) if r == "delete" else None)
        dialog.present(self)

    # ---------------------------------------------------------------- servers

    def _servers_page(self):
        self.servers_page = Adw.PreferencesPage(title=_("Servers"), icon_name="network-server-symbolic")
        self.servers_group = None
        self._fill_servers()
        return self.servers_page

    def _fill_servers(self):
        if self.servers_group is not None:
            self.servers_page.remove(self.servers_group)
        group = Adw.PreferencesGroup(
            title=_("Favorite Servers"),
            description=_("Shown in the sidebar. Rename a server by editing its name."))
        add = Gtk.Button(icon_name="list-add-symbolic", css_classes=["flat"], tooltip_text=_("Connect to Server…"))
        add.connect("clicked", self._add_server)
        group.set_header_suffix(add)
        for server in servers.saved_servers(self.settings):
            uri = server["uri"]
            row = Adw.EntryRow(title=uri, text=server["name"], show_apply_button=True)
            row.add_prefix(Gtk.Image(icon_name="network-server-symbolic"))
            row.connect("apply", lambda r, u=uri: servers.rename_server(self.settings, u, r.get_text()))
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                tooltip_text=_("Remove from Favorites"))
            remove.connect("clicked", lambda _b, u=uri: servers.remove_server(self.settings, u))
            row.add_suffix(remove)
            group.add(row)
        self.servers_group = group
        self.servers_page.add(group)

    def _add_server(self, *_args):
        window = self.app.get_active_window()
        self.close()
        if window is not None:
            servers.ConnectDialog(window).present(window)

    # --------------------------------------------------------------- advanced

    def _advanced_page(self):
        page = Adw.PreferencesPage(title=_("Advanced"), icon_name="emblem-system-symbolic")
        group = Adw.PreferencesGroup(title=_("Files"))
        group.add(_switch(self.settings, "show_extensions", _("Show all filename extensions")))
        group.add(_switch(self.settings, "show_hidden", _("Show hidden files")))
        group.add(_switch(self.settings, "folders_first", _("Keep folders on top"),
                          _("In icon, list and column views")))
        page.add(group)
        return page
