"""Network servers: "Connect to Server" (Ctrl+K), favourites, mounting.

Everything goes through GVfs, so Galet supports whatever GNOME supports:
SMB/Windows shares, SFTP/SSH, FTP, WebDAV (Nextcloud, kDrive...), AFP, NFS.
Passwords are requested with the standard GNOME dialog and can be remembered
in the GNOME keyring.
"""

from gi.repository import Adw, Gio, GLib, Gtk

from .i18n import _

REMOTE_SCHEMES = {"smb", "sftp", "ssh", "ftp", "ftps", "dav", "davs", "afp", "nfs", "webdav", "webdavs"}
MAX_RECENT = 8


# ------------------------------------------------------------------ addresses

def normalize_address(text):
    """Accept what people actually type: "nas.local", "\\\\nas\\share", "me@host"."""
    text = text.strip()
    if text.startswith("\\\\"):
        text = "smb:" + text.replace("\\", "/")
    elif "://" not in text:
        text = ("sftp://" if "@" in text else "smb://") + text
    return text


def server_name(uri):
    try:
        parsed = GLib.Uri.parse(uri, GLib.UriFlags.NONE)
    except GLib.Error:
        return uri
    host = parsed.get_host() or uri
    first = parsed.get_path().strip("/").split("/")[0]
    return f"{host} — {GLib.Uri.unescape_string(first) or first}" if first else host


def needs_mount(gfile):
    return (gfile.get_uri_scheme() or "") in REMOTE_SCHEMES


def find_mount(gfile, volume_monitor=None):
    for mount in (volume_monitor or Gio.VolumeMonitor.get()).get_mounts():
        root = mount.get_root()
        if gfile.equal(root) or gfile.has_prefix(root):
            return mount
    return None


def find_volume(gfile, volume_monitor=None):
    """A not-yet-mounted volume for this address (e.g. a GNOME Online Accounts
    share such as kDrive or Nextcloud, which knows the credentials)."""
    for volume in (volume_monitor or Gio.VolumeMonitor.get()).get_volumes():
        root = volume.get_activation_root()
        if root is not None and (gfile.equal(root) or gfile.has_prefix(root)):
            return volume
    return None


def mount_volume(window, volume, callback):
    """Mount a Gio.Volume, then call ``callback(root)`` with its root folder."""

    def done(source, result, *_args):
        try:
            source.mount_finish(result)
        except GLib.Error as err:
            if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                window.toast(_("Could not connect to the server: {error}").format(error=err.message))
            return
        mount = source.get_mount()
        if mount is not None:
            callback(mount.get_root())

    window.toast(_("Connecting to {server}…").format(server=volume.get_name()))
    volume.mount(Gio.MountMountFlags.NONE, Gtk.MountOperation.new(window), None, done)


# --------------------------------------------------------- saved servers list

def saved_servers(settings):
    return [dict(s) for s in settings.get("servers", []) if isinstance(s, dict) and s.get("uri")]


def add_server(settings, uri, name=None):
    servers = saved_servers(settings)
    if not any(s["uri"] == uri for s in servers):
        servers.append({"uri": uri, "name": name or server_name(uri)})
        settings.set("servers", servers)


def remove_server(settings, uri):
    settings.set("servers", [s for s in saved_servers(settings) if s["uri"] != uri])


def rename_server(settings, uri, name):
    servers = saved_servers(settings)
    for server in servers:
        if server["uri"] == uri and name.strip():
            server["name"] = name.strip()
    settings.set("servers", servers)


def recent_servers(settings):
    return [u for u in settings.get("recent_servers", []) if isinstance(u, str)]


def remember_recent(settings, uri):
    recent = [uri] + [u for u in recent_servers(settings) if u != uri]
    settings.set("recent_servers", recent[:MAX_RECENT])


# ------------------------------------------------------------------- mounting

def ensure_mounted(window, gfile, callback):
    """Call ``callback()`` once ``gfile`` is reachable, mounting it if needed."""
    if not needs_mount(gfile):
        callback()
        return

    def on_mounted(source, result, *_args):
        try:
            source.mount_enclosing_volume_finish(result)
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                return  # the user cancelled the password dialog
            if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                window.toast(_("Could not connect to the server: {error}").format(error=err.message))
                return
        callback()

    def on_found(source, result, *_args):
        try:
            source.find_enclosing_mount_finish(result)
            callback()
            return
        except GLib.Error:
            pass
        volume = find_volume(gfile)
        if volume is not None:
            mount_volume(window, volume, lambda _root: callback())
            return
        window.toast(_("Connecting to {server}…").format(server=server_name(gfile.get_uri())))
        operation = Gtk.MountOperation.new(window)
        source.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, None, on_mounted)

    gfile.find_enclosing_mount_async(GLib.PRIORITY_DEFAULT, None, on_found)


def unmount(window, mount):
    name = mount.get_name()

    def done(source, result, *_args):
        try:
            if eject:
                source.eject_with_operation_finish(result)
            else:
                source.unmount_with_operation_finish(result)
        except GLib.Error as err:
            if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                window.toast(_("Could not disconnect: {error}").format(error=err.message))
            return
        window.toast(_("“{name}” disconnected").format(name=name))

    operation = Gtk.MountOperation.new(window)
    eject = mount.can_eject()
    if eject:
        mount.eject_with_operation(Gio.MountUnmountFlags.NONE, operation, None, done)
    else:
        mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, operation, None, done)


# ------------------------------------------------------------- connect dialog

class ConnectDialog(Adw.Dialog):
    """Finder's "Connect to Server" window."""

    def __init__(self, window):
        super().__init__(title=_("Connect to Server"), content_width=520, content_height=560)
        self.window = window
        self.settings = window.settings

        self.entry = Adw.EntryRow(title=_("Server Address"))
        self.entry.connect("entry-activated", lambda *_a: self._connect())
        favorite = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                              tooltip_text=_("Add to Favorite Servers"))
        favorite.connect("clicked", lambda *_a: self._add_favorite())
        self.entry.add_suffix(favorite)

        examples = _("Examples: {examples}").format(examples=" · ".join((
            "smb://nas.local/share", "sftp://user@server.com", "ftp://ftp.example.com",
            "davs://cloud.example.com/remote.php/webdav")))
        address = Adw.PreferencesGroup(description=examples)
        address.add(self.entry)

        self.page = Adw.PreferencesPage()
        self.page.add(address)
        self.lists = None
        self._fill_lists()

        connect = Gtk.Button(label=_("Connect"), halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=12,
                             css_classes=["suggested-action", "pill"])
        connect.connect("clicked", lambda *_a: self._connect())

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(self.page)
        toolbar.add_bottom_bar(connect)
        self.set_child(toolbar)
        self.set_focus(self.entry)

    def _fill_lists(self):
        if self.lists is not None:
            for group in self.lists:
                self.page.remove(group)
        favorites = Adw.PreferencesGroup(title=_("Favorite Servers"))
        servers = saved_servers(self.settings)
        if not servers:
            favorites.set_description(_("Type an address and press + to keep it here and in the sidebar."))
        for server in servers:
            row = self._server_row(server["name"], server["uri"])
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                tooltip_text=_("Remove from Favorites"))
            remove.connect("clicked", lambda _b, uri=server["uri"]: (remove_server(self.settings, uri),
                                                                     self._fill_lists()))
            row.add_suffix(remove)
            favorites.add(row)

        recent = Adw.PreferencesGroup(title=_("Recent Servers"))
        for uri in recent_servers(self.settings):
            recent.add(self._server_row(server_name(uri), uri))
        self.lists = [favorites] + ([recent] if recent_servers(self.settings) else [])
        for group in self.lists:
            self.page.add(group)

    def _server_row(self, title, uri):
        row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(uri),
                            activatable=True)
        row.add_prefix(Gtk.Image(icon_name="network-server-symbolic"))
        row.connect("activated", lambda _r: (self.entry.set_text(uri), self._connect()))
        return row

    def _address(self):
        text = self.entry.get_text().strip()
        return normalize_address(text) if text else None

    def _add_favorite(self):
        uri = self._address()
        if uri:
            add_server(self.settings, uri)
            self._fill_lists()

    def _connect(self):
        uri = self._address()
        if not uri:
            return
        remember_recent(self.settings, uri)
        self.close()
        self.window.open_server(Gio.File.new_for_uri(uri))
