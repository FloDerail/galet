"""Finder-like sidebar: Favourites, Locations and Tags."""

from pathlib import Path

from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import dnd, fileops, search, servers
from .i18n import _
from .model import Location, display_name
from .widgets import TagDots

SPECIAL_DIRS = (
    ("desktop", GLib.UserDirectory.DIRECTORY_DESKTOP, "user-desktop-symbolic"),
    ("documents", GLib.UserDirectory.DIRECTORY_DOCUMENTS, "folder-documents-symbolic"),
    ("downloads", GLib.UserDirectory.DIRECTORY_DOWNLOAD, "folder-download-symbolic"),
    ("pictures", GLib.UserDirectory.DIRECTORY_PICTURES, "folder-pictures-symbolic"),
    ("music", GLib.UserDirectory.DIRECTORY_MUSIC, "folder-music-symbolic"),
    ("videos", GLib.UserDirectory.DIRECTORY_VIDEOS, "folder-videos-symbolic"),
)

BOOKMARKS = Path(GLib.get_user_config_dir()) / "gtk-3.0" / "bookmarks"


class Sidebar(Gtk.ScrolledWindow):
    def __init__(self, window):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.window = window
        self.tagstore = window.tagstore
        self.settings = window.settings
        self.listbox = Gtk.ListBox(css_classes=["navigation-sidebar"])
        self.listbox.connect("row-activated", self._on_row_activated)
        self.set_child(self.listbox)
        self._current = None
        self._rebuild_id = 0

        self._volumes = Gio.VolumeMonitor.get()
        self._handlers = [(self._volumes, self._volumes.connect(signal, self._queue_rebuild))
                          for signal in ("mount-added", "mount-removed", "mount-changed",
                                         "volume-added", "volume-removed", "volume-changed")]
        self._handlers.append((self.tagstore, self.tagstore.connect("tags-changed", self._queue_rebuild)))
        self._handlers.append((self.settings, self.settings.connect(
            "changed", lambda _s, key: self._queue_rebuild() if key in ("sidebar", "servers", "smart_folders")
            else None)))
        self._bookmarks_monitor = None
        try:
            self._bookmarks_monitor = Gio.File.new_for_path(str(BOOKMARKS)).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
            self._handlers.append((self._bookmarks_monitor,
                                   self._bookmarks_monitor.connect("changed", self._queue_rebuild)))
        except GLib.Error:
            pass
        self.rebuild()

    def teardown(self):
        for obj, handler in self._handlers:
            obj.disconnect(handler)
        self._handlers = []
        if self._bookmarks_monitor is not None:
            self._bookmarks_monitor.cancel()
        if self._rebuild_id:
            GLib.source_remove(self._rebuild_id)
            self._rebuild_id = 0

    # --------------------------------------------------------------- building

    def _queue_rebuild(self, *_args):
        if not self._rebuild_id:
            self._rebuild_id = GLib.timeout_add(100, self.rebuild)

    def rebuild(self):
        self._rebuild_id = 0
        self.listbox.remove_all()
        home = Gio.File.new_for_path(GLib.get_home_dir())

        shows = self.settings.sidebar_shows
        shown = set()

        def place(title, gfile, icon):
            shown.add(gfile.get_uri())
            self._row(title, Location(gfile), icon, droppable=gfile.get_uri_scheme() == "file")

        self._heading(_("Favorites"))
        if shows("recent"):
            place(_("Recent"), Gio.File.new_for_uri("recent:///"), "document-open-recent-symbolic")
        if shows("home"):
            place(display_name(home), home, "user-home-symbolic")
        for key, directory, icon in SPECIAL_DIRS:
            path = GLib.get_user_special_dir(directory)
            if shows(key) and path and Path(path) != Path(GLib.get_home_dir()) and Path(path).is_dir():
                gfile = Gio.File.new_for_path(path)
                place(display_name(gfile), gfile, icon)
        if shows("bookmarks"):
            for gfile, label in self._read_bookmarks():
                if gfile.get_uri() not in shown:
                    place(label, gfile, "folder-symbolic")

        saved = servers.saved_servers(self.settings)
        saved_files = [Gio.File.new_for_uri(s["uri"]) for s in saved]

        self._heading(_("Locations"))
        if shows("computer"):
            self._row(_("Computer"), Location(Gio.File.new_for_path("/")), "drive-harddisk-symbolic")
        if shows("mounts"):
            for mount in self._volumes.get_mounts():
                root = mount.get_root()
                if mount.is_shadowed() or (shows("servers") and any(
                        f.equal(root) or f.has_prefix(root) for f in saved_files)):
                    continue  # shown in the Servers section instead
                self._row(mount.get_name(), Location(root), gicon=mount.get_symbolic_icon(),
                          mount=mount if mount.can_unmount() else None)
            for volume in self._volumes.get_volumes():
                if volume.get_mount() is not None or not volume.can_mount():
                    continue
                root = volume.get_activation_root()
                drive = volume.get_drive()
                if root is None and not (drive is not None and drive.is_removable()):
                    continue  # internal partitions stay hidden, like in GNOME Files
                if root is not None and shows("servers") and any(
                        f.equal(root) or f.has_prefix(root) for f in saved_files):
                    continue
                self._volume_row(volume)
        if shows("network"):
            self._row(_("Network"), Location(Gio.File.new_for_uri("network:///")), "network-workgroup-symbolic",
                      droppable=False)
        if shows("trash"):
            self._row(_("Trash"), Location(Gio.File.new_for_uri("trash:///")), "user-trash-symbolic",
                      trash=True)

        if shows("servers") and saved:
            self._heading(_("Servers"))
            for server, gfile in zip(saved, saved_files):
                mount = servers.find_mount(gfile, self._volumes)
                self._row(server["name"], Location(gfile), "network-server-symbolic", mount=mount,
                          server_uri=server["uri"])

        smart = search.smart_folders(self.settings)
        if smart:
            self._heading(_("Smart Folders"))
            for name, query in smart:
                self._row(name, Location(search=query), "folder-saved-search-symbolic", droppable=False,
                          smart_name=name)

        visible_tags = [t for t in self.tagstore.tags if t.get("visible", True)]
        if shows("tags") and visible_tags:
            self._heading(_("Tags"))
            for tag in visible_tags:
                self._row(tag["name"], Location(tag=tag["name"]), color=tag["color"] or "")

        if self._current is not None:
            self.select_location(self._current)
        return GLib.SOURCE_REMOVE

    def _read_bookmarks(self):
        result = []
        try:
            lines = BOOKMARKS.read_text(encoding="utf-8").splitlines()
        except OSError:
            return result
        for line in lines:
            if not line.strip():
                continue
            uri, _sep, label = line.partition(" ")
            gfile = Gio.File.new_for_uri(uri)
            result.append((gfile, label or display_name(gfile)))
        return result

    def _heading(self, text):
        label = Gtk.Label(label=text, xalign=0, css_classes=["dim-label", "caption-heading", "sidebar-heading"])
        self.listbox.append(Gtk.ListBoxRow(child=label, activatable=False, selectable=False))

    def _row(self, title, location, icon_name=None, gicon=None, color=None, mount=None,
             server_uri=None, trash=False, droppable=True, smart_name=None):
        box = Gtk.Box(spacing=10)
        if color is not None:
            dots = TagDots(self.tagstore, 12)
            dots.set_colors([color or None])
            dots.set_margin_start(3)
            dots.set_margin_end(3)
            box.append(dots)
        elif gicon is not None:
            box.append(Gtk.Image(gicon=gicon))
        else:
            box.append(Gtk.Image(icon_name=icon_name))
        box.append(Gtk.Label(label=title, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
        if mount is not None:
            eject = Gtk.Button(icon_name="media-eject-symbolic", css_classes=["flat", "circular", "sidebar-eject"],
                               tooltip_text=_("Disconnect"), valign=Gtk.Align.CENTER)
            eject.connect("clicked", lambda _b: self.window.unmount(mount))
            box.append(eject)
        row = Gtk.ListBoxRow(child=box)
        row.location = location

        menu = []
        if location.is_tag:
            name = location.tag
            dnd.add_drop_target(row, lambda: name, lambda files, _d, _a: self.window.drop_on_tag(files, name),
                                fixed_action=Gdk.DragAction.COPY)
            menu.append((_("Delete Tag…"), "win.delete-tag", name))
        elif trash:
            dnd.add_drop_target(row, lambda: location.gfile,
                                lambda files, _d, _a: fileops.trash_files(self.window, files),
                                fixed_action=Gdk.DragAction.MOVE)
        elif droppable:
            dnd.add_drop_target(row, lambda: location.gfile, self.window.drop_files)
            dnd.add_spring_load(row, lambda: location.gfile, lambda f: self.window.navigate(Location(f)))
        if smart_name is not None:
            menu.append((_("Remove Smart Folder"), "win.remove-smart-folder", smart_name))
        if server_uri is not None:
            if mount is not None:
                menu.append((_("Disconnect"), "win.disconnect", server_uri))
            menu.append((_("Remove from Favorites"), "win.remove-server", server_uri))
        if menu:
            gesture = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
            gesture.connect("pressed", lambda _g, _n, x, y: self._popup_menu(row, x, y, menu))
            row.add_controller(gesture)
        self.listbox.append(row)

    def _volume_row(self, volume):
        """An unmounted drive or online account: clicking it connects it."""
        box = Gtk.Box(spacing=10)
        box.append(Gtk.Image(gicon=volume.get_symbolic_icon()))
        box.append(Gtk.Label(label=volume.get_name(), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END,
                             css_classes=["dim-label"]))
        row = Gtk.ListBoxRow(child=box, tooltip_text=_("Click to connect"))
        row.location = None
        row.volume = volume
        self.listbox.append(row)

    def _popup_menu(self, row, x, y, entries):
        menu = Gio.Menu()
        for label, action, target in entries:
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(action, GLib.Variant("s", target))
            menu.append_item(item)
        popover = Gtk.PopoverMenu.new_from_model(menu)
        popover.set_parent(row)
        popover.set_has_arrow(False)
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
        popover.set_pointing_to(rect)
        popover.connect("closed", lambda p: GLib.idle_add(p.unparent))
        popover.popup()

    # ------------------------------------------------------------- behaviour

    def _on_row_activated(self, _listbox, row):
        volume = getattr(row, "volume", None)
        if volume is not None:
            servers.mount_volume(self.window, volume, lambda root: self.window.navigate(Location(root)))
            return
        location = getattr(row, "location", None)
        if location is not None:
            self.window.navigate(location)

    def select_location(self, location):
        self._current = location
        row = self.listbox.get_first_child()
        while row is not None:
            if getattr(row, "location", None) == location:
                self.listbox.select_row(row)
                return
            row = row.get_next_sibling()
        self.listbox.unselect_all()
