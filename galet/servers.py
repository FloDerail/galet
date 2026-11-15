"""Network servers: the server manager (Ctrl+K), saved servers, logins, mounting.

Everything goes through GVfs, so Galet supports whatever GNOME supports:
SMB/Windows shares, SFTP/SSH, FTP, WebDAV (Nextcloud, kDrive...), AFP, NFS.

A saved server is a small card (protocol, host, port, user name, folder). Its
password, when the user chooses to keep it, lives in the GNOME keyring — never in
the settings file or in backups. When a server asks for a login, Galet shows its
own login window, pre-filled with what it knows.
"""

import logging
import subprocess
import uuid
from urllib.parse import quote

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .i18n import _

log = logging.getLogger("galet")

REMOTE_SCHEMES = {"smb", "sftp", "ssh", "ftp", "ftps", "dav", "davs", "afp", "nfs", "webdav", "webdavs"}
MAX_RECENT = 8

# (scheme, label, default port, icon)
PROTOCOLS = (
    ("sftp", "SFTP / SSH", 22, "utilities-terminal-symbolic"),
    ("smb", "SMB — Windows, NAS", 445, "network-workgroup-symbolic"),
    ("davs", "WebDAV (HTTPS) — Nextcloud, kDrive…", 443, "folder-remote-symbolic"),
    ("dav", "WebDAV (HTTP)", 80, "folder-remote-symbolic"),
    ("ftp", "FTP", 21, "network-server-symbolic"),
    ("ftps", "FTPS", 21, "network-server-symbolic"),
    ("nfs", "NFS", 2049, "network-server-symbolic"),
    ("afp", "AFP — Mac", 548, "network-server-symbolic"),
)
SCHEMES = [p[0] for p in PROTOCOLS]
ALIASES = {"ssh": "sftp", "webdav": "dav", "webdavs": "davs"}


def protocol_info(scheme):
    scheme = ALIASES.get(scheme, scheme)
    for info in PROTOCOLS:
        if info[0] == scheme:
            return info
    return (scheme, scheme.upper(), 0, "network-server-symbolic")


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


def parse_uri(uri):
    """Split an address into the fields of a server card."""
    fields = {"protocol": "smb", "host": "", "port": 0, "user": "", "domain": "", "path": ""}
    try:
        parsed = GLib.Uri.parse(uri, GLib.UriFlags.NONE)
    except GLib.Error:
        return fields
    fields["protocol"] = ALIASES.get(parsed.get_scheme() or "smb", parsed.get_scheme() or "smb")
    fields["host"] = parsed.get_host() or ""
    fields["port"] = max(parsed.get_port(), 0)
    user = GLib.Uri.unescape_string(parsed.get_user() or "") or ""
    if ";" in user:
        fields["domain"], user = user.split(";", 1)
    fields["user"] = user
    fields["path"] = (GLib.Uri.unescape_string(parsed.get_path() or "") or "").strip("/")
    return fields


def build_uri(server):
    scheme = server.get("protocol") or "smb"
    host = (server.get("host") or "").strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6
    userinfo = ""
    user = (server.get("user") or "").strip()
    if user:
        userinfo = quote(user, safe="")
        domain = (server.get("domain") or "").strip()
        if domain and scheme == "smb":
            userinfo = quote(domain, safe="") + ";" + userinfo
        userinfo += "@"
    port = int(server.get("port") or 0)
    port_part = f":{port}" if port and port != protocol_info(scheme)[2] else ""
    path = (server.get("path") or "").strip().strip("/")
    path_part = "/" + quote(path, safe="/") if path else "/"
    return f"{scheme}://{userinfo}{host}{port_part}{path_part}"


def describe(server):
    """"SFTP · florian@nas.local:2222" """
    label = protocol_info(server.get("protocol", ""))[1].split(" ")[0]
    user = server.get("user") or ""
    port = int(server.get("port") or 0)
    where = (f"{user}@" if user else "") + (server.get("host") or "")
    if port and port != protocol_info(server.get("protocol", ""))[2]:
        where += f":{port}"
    if server.get("path"):
        where += "/" + server["path"]
    return f"{label} · {where}"


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


# ------------------------------------------------------------------ passwords

def _schema():
    gi_ = __import__("gi")
    gi_.require_version("Secret", "1")
    from gi.repository import Secret
    return Secret, Secret.Schema.new("io.github.FloDerail.Galet.Server", Secret.SchemaFlags.NONE,
                                     {"server": Secret.SchemaAttributeType.STRING})


def get_password(server_id):
    if not server_id:
        return ""
    try:
        secret, schema = _schema()
        return secret.password_lookup_sync(schema, {"server": server_id}, None) or ""
    except Exception:  # noqa: BLE001  keyring unavailable
        return ""


def set_password(server_id, password, label=""):
    try:
        secret, schema = _schema()
        if password:
            secret.password_store_sync(schema, {"server": server_id}, secret.COLLECTION_DEFAULT,
                                       _("Galet server: {name}").format(name=label or server_id), password, None)
        else:
            secret.password_clear_sync(schema, {"server": server_id}, None)
        return True
    except Exception as err:  # noqa: BLE001
        log.warning("Could not use the keyring for a server password: %s", err)
        return False


# --------------------------------------------------------- saved servers list

def _complete(server):
    """Old entries only had a uri and a name: fill in the card fields."""
    server = dict(server)
    if not server.get("host"):
        server.update({k: v for k, v in parse_uri(server["uri"]).items() if not server.get(k)})
    server.setdefault("id", uuid.uuid5(uuid.NAMESPACE_URL, server["uri"]).hex)
    server.setdefault("name", server_name(server["uri"]))
    return server


def _vault(settings):
    from . import vault
    return vault.get(settings)


def vault_locked(settings):
    return _vault(settings).locked


def saved_servers(settings):
    return [_complete(s) for s in _vault(settings).servers() if isinstance(s, dict) and s.get("uri")]


def _store(settings, servers):
    _vault(settings).set_servers(servers)


def save_server(settings, server):
    """Add or update a server card (matched by id); returns the stored card."""
    server = dict(server)
    server.setdefault("id", uuid.uuid4().hex)
    server["uri"] = build_uri(server)
    server["name"] = (server.get("name") or "").strip() or server_name(server["uri"])
    servers = saved_servers(settings)
    for index, existing in enumerate(servers):
        if existing["id"] == server["id"]:
            servers[index] = server
            break
    else:
        servers.append(server)
    _store(settings, servers)
    return server


def add_server(settings, uri, name=None):
    if not any(s["uri"] == uri for s in saved_servers(settings)):
        server = parse_uri(uri)
        server["name"] = name or server_name(uri)
        return save_server(settings, server)
    return None


def remove_server(settings, uri):
    for server in saved_servers(settings):
        if server["uri"] == uri:
            set_password(server["id"], "")
    _store(settings, [s for s in saved_servers(settings) if s["uri"] != uri])


def rename_server(settings, uri, name):
    servers = saved_servers(settings)
    for server in servers:
        if server["uri"] == uri and name.strip():
            server["name"] = name.strip()
    _store(settings, servers)


def server_for(settings, gfile):
    """The saved server an address belongs to (same protocol, host and port)."""
    target = parse_uri(gfile.get_uri())
    best = None
    for server in saved_servers(settings):
        if (server["protocol"], server["host"].lower(), int(server.get("port") or 0) or protocol_info(server["protocol"])[2]) != \
                (target["protocol"], target["host"].lower(), target["port"] or protocol_info(target["protocol"])[2]):
            continue
        if target["user"] and server.get("user") and target["user"] != server["user"]:
            continue
        if best is None or len(server.get("path", "")) > len(best.get("path", "")):
            if not server.get("path") or target["path"].startswith(server["path"]):
                best = server
    return best


def recent_servers(settings):
    return [u for u in _vault(settings).recent() if isinstance(u, str)]


def remember_recent(settings, uri):
    recent = [uri] + [u for u in recent_servers(settings) if u != uri]
    _vault(settings).set_recent(recent[:MAX_RECENT])


# ------------------------------------------------------------- login window

class _Login:
    """Answers GVfs' password requests: saved password first, then our own login window."""

    def __init__(self, window, gfile):
        self.window = window
        self.server = server_for(window.settings, gfile) if gfile is not None else None
        self.title = self.server["name"] if self.server else (server_name(gfile.get_uri()) if gfile else "")
        self.tries = 0
        self.operation = Gtk.MountOperation.new(window)
        self.operation.connect("ask-password", self._on_ask_password)
        self.operation._galet_login = self  # keep alive as long as the operation

    def _on_ask_password(self, operation, message, default_user, default_domain, flags):
        operation.stop_emission_by_name("ask-password")
        self.tries += 1
        server = self.server or {}
        user = server.get("user") or default_user or ""
        domain = server.get("domain") or default_domain or ""
        password = get_password(server.get("id")) if server else ""
        need_user = bool(flags & Gio.AskPasswordFlags.NEED_USERNAME)
        need_password = bool(flags & Gio.AskPasswordFlags.NEED_PASSWORD)
        if self.tries == 1 and server and (password or not need_password) and (user or not need_user):
            self._reply(user, password, domain)
            return
        self._show_dialog(message, user, domain, flags, wrong=self.tries > 1)

    def _reply(self, user, password, domain, anonymous=False, save_quick=False):
        op = self.operation
        if anonymous:
            op.set_anonymous(True)
        else:
            op.set_username(user)
            op.set_password(password)
            if domain:
                op.set_domain(domain)
        op.set_password_save(Gio.PasswordSave.PERMANENTLY if save_quick else Gio.PasswordSave.NEVER)
        op.reply(Gio.MountOperationResult.HANDLED)

    def _show_dialog(self, message, user, domain, flags, wrong):
        dialog = Adw.AlertDialog(heading=_("Log in to {server}").format(server=self.title))
        body = _("Wrong user name or password, try again.") if wrong else \
            _("This server asks for a user name and a password.")
        dialog.set_body(body)
        group = Adw.PreferencesGroup()
        user_row = Adw.EntryRow(title=_("User Name"), text=user)
        domain_row = Adw.EntryRow(title=_("Domain (optional)"), text=domain,
                                  visible=bool(flags & Gio.AskPasswordFlags.NEED_DOMAIN))
        password_row = Adw.PasswordEntryRow(title=_("Password"),
                                            visible=bool(flags & Gio.AskPasswordFlags.NEED_PASSWORD))
        user_row.connect("entry-activated", lambda *_a: password_row.grab_focus())
        anonymous = Adw.SwitchRow(title=_("Connect as Guest"),
                                  visible=bool(flags & Gio.AskPasswordFlags.ANONYMOUS_SUPPORTED))
        anonymous.connect("notify::active", lambda row, _p: [w.set_sensitive(not row.get_active())
                                                              for w in (user_row, domain_row, password_row)])
        remember = Adw.SwitchRow(title=_("Remember Password"), subtitle=_("Kept in the GNOME keyring"),
                                 active=bool(self.server))
        for row in (anonymous, user_row, domain_row, password_row, remember):
            group.add(row)
        dialog.set_extra_child(group)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("connect", _("Connect"))
        dialog.set_response_appearance("connect", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("connect")
        dialog.set_close_response("cancel")

        answered = []

        def on_response(_dialog, response):
            if answered:
                return  # closing after Enter emits the close response: already answered
            answered.append(response)
            if response != "connect":
                self.operation.reply(Gio.MountOperationResult.ABORTED)
                return
            if anonymous.get_active():
                self._reply("", "", "", anonymous=True)
                return
            user_name, password = user_row.get_text().strip(), password_row.get_text()
            domain_name = domain_row.get_text().strip()
            keep = remember.get_active()
            if self.server is not None:
                if user_name and user_name != self.server.get("user"):
                    self.server["user"] = user_name
                    self.server = save_server(self.window.settings, self.server)
                set_password(self.server["id"], password if keep else "", self.server["name"])
            self._reply(user_name, password, domain_name, save_quick=keep and self.server is None)

        dialog.connect("response", on_response)

        def submit(*_args):
            on_response(dialog, "connect")
            dialog.close()

        password_row.connect("entry-activated", submit)
        dialog.connect("map", lambda *_a: GLib.idle_add(
            lambda: (password_row if user else user_row).grab_focus() and False))
        dialog.present(self.window)


def mount_operation(window, gfile=None):
    return _Login(window, gfile).operation


def _connection_failed(window, gfile, error):
    log.warning("Could not connect to %s: %s", gfile.get_uri() if gfile else "?", error)
    server = server_for(window.settings, gfile) if gfile is not None else None
    name = server["name"] if server else (server_name(gfile.get_uri()) if gfile else "")
    dialog = Adw.AlertDialog(heading=_("Could not connect to {server}").format(server=name), body=error)
    dialog.add_response("ok", _("OK"))
    if server is not None:
        dialog.add_response("edit", _("Edit Server…"))
        dialog.connect("response", lambda _d, r: r == "edit" and ServerEditor(window, server).present(window))
    dialog.present(window)


# ------------------------------------------------------------------- mounting

def mount_volume(window, volume, callback):
    """Mount a Gio.Volume, then call ``callback(root)`` with its root folder."""

    def done(source, result, *_args):
        try:
            source.mount_finish(result)
        except GLib.Error as err:
            if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                _connection_failed(window, source.get_activation_root(), err.message)
            return
        mount = source.get_mount()
        if mount is not None:
            callback(mount.get_root())

    window.toast(_("Connecting to {server}…").format(server=volume.get_name()))
    volume.mount(Gio.MountMountFlags.NONE, mount_operation(window, volume.get_activation_root()), None, done)


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
                return  # the user cancelled the login window
            if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                _connection_failed(window, gfile, err.message)
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
        source.mount_enclosing_volume(Gio.MountMountFlags.NONE, mount_operation(window, gfile), None, on_mounted)

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


def open_ssh(window, server):
    """Open an SSH session to the server in the system terminal."""
    panel = getattr(window, "terminal_panel", None)
    from . import terminal
    if panel is not None and terminal.available():  # built-in terminal
        window.show_terminal(True, create=False)
        panel.open_ssh(server)
        return
    from .sandbox import find_program

    args = ["ssh"]
    port = int(server.get("port") or 0)
    if port and port != 22:
        args += ["-p", str(port)]
    args.append((f"{server['user']}@" if server.get("user") else "") + server["host"])
    for program in ("ptyxis", "gnome-terminal", "kgx", "xdg-terminal-exec"):
        command = find_program(program)
        if command:
            extra = args if program == "xdg-terminal-exec" else ["--", *args]
            subprocess.Popen([*command, *extra], start_new_session=True)
            return
    window.toast(_("No terminal application found."))


# ------------------------------------------------------------ master password

def master_password_dialog(parent, settings, on_done=None):
    """Set, change or remove the master password that locks the server list."""
    vault = _vault(settings)
    has = vault.uses_master
    dialog = Adw.AlertDialog(
        heading=_("Change Master Password") if has else _("Set a Master Password"),
        body=_("Your server list is encrypted. With a master password, it stays locked until you type it "
               "(once per session). If you forget it, the server list cannot be recovered."))
    group = Adw.PreferencesGroup()
    first = Adw.PasswordEntryRow(title=_("New Master Password"))
    second = Adw.PasswordEntryRow(title=_("Confirm"))
    group.add(first)
    group.add(second)
    dialog.set_extra_child(group)
    dialog.add_response("cancel", _("Cancel"))
    if has:
        dialog.add_response("remove", _("Remove"))
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.add_response("save", _("Save"))
    dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_response_enabled("save", False)
    dialog.set_close_response("cancel")

    def check(*_args):
        text = first.get_text()
        dialog.set_response_enabled("save", len(text) >= 6 and text == second.get_text())
        second.remove_css_class("error") if not second.get_text() or text.startswith(second.get_text()) \
            else second.add_css_class("error")

    first.connect("changed", check)
    second.connect("changed", check)

    def on_response(_dialog, response):
        if response not in ("save", "remove"):
            return
        try:
            vault.set_master_password(first.get_text() if response == "save" else None)
        except Exception as err:  # noqa: BLE001
            log.warning("Cannot change the master password: %s", err)
            return
        if on_done:
            on_done()

    dialog.connect("response", on_response)
    dialog.present(parent)


# ---------------------------------------------------------------- server card

class ServerEditor(Adw.Dialog):
    """Create or edit a saved server."""

    def __init__(self, window, server=None, on_saved=None):
        editing = bool(server and server.get("id"))
        super().__init__(title=_("Edit Server") if editing else _("New Server"), content_width=520,
                         content_height=640)
        self.window = window
        self.server = dict(server or {"protocol": "sftp"})
        self.on_saved = on_saved

        self.name_row = Adw.EntryRow(title=_("Name"), text=self.server.get("name", ""))
        self.protocol_row = Adw.ComboRow(title=_("Protocol"),
                                         model=Gtk.StringList.new([p[1] for p in PROTOCOLS]))
        scheme = ALIASES.get(self.server.get("protocol"), self.server.get("protocol"))
        self.protocol_row.set_selected(SCHEMES.index(scheme) if scheme in SCHEMES else 0)
        self.host_row = Adw.EntryRow(title=_("Host (name or IP address)"), text=self.server.get("host", ""))
        self.port_row = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.port_row.set_title(_("Port"))
        self.path_row = Adw.EntryRow(title=_("Folder or Share (optional)"), text=self.server.get("path", ""))
        self.address = Adw.PreferencesGroup(title=_("Server"))
        for row in (self.name_row, self.protocol_row, self.host_row, self.port_row, self.path_row):
            self.address.add(row)

        self.user_row = Adw.EntryRow(title=_("User Name"), text=self.server.get("user", ""))
        self.domain_row = Adw.EntryRow(title=_("Domain (optional)"), text=self.server.get("domain", ""))
        self.password_row = Adw.PasswordEntryRow(title=_("Password"))
        if editing:
            self.password_row.set_text(get_password(self.server.get("id")))
        login = Adw.PreferencesGroup(
            title=_("Login"),
            description=_("The password is kept in the GNOME keyring, never in a file. Leave it empty to be "
                          "asked when connecting. For SFTP, your SSH keys (~/.ssh) are used automatically."))
        for row in (self.user_row, self.domain_row, self.password_row):
            login.add(row)

        self.page = Adw.PreferencesPage()
        self.page.add(self.address)
        self.page.add(login)
        if editing:
            delete = Gtk.Button(label=_("Delete Server"), halign=Gtk.Align.CENTER,
                                css_classes=["destructive-action", "pill"])
            delete.connect("clicked", lambda *_a: self._delete())
            danger = Adw.PreferencesGroup()
            danger.add(delete)
            self.page.add(danger)

        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_a: self.close())
        self.save_button = Gtk.Button(label=_("Save"), css_classes=["suggested-action"])
        self.save_button.connect("clicked", lambda *_a: self._save())
        header.pack_start(cancel)
        header.pack_end(self.save_button)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.page)
        self.set_child(toolbar)

        self._port_is_default = not self.server.get("port")
        self.port_row.set_value(int(self.server.get("port") or 0) or self._scheme_info()[2] or 1)
        self.port_row.connect("notify::value", self._on_port)
        self.protocol_row.connect("notify::selected", lambda *_a: self._on_protocol())
        for row in (self.name_row, self.host_row, self.path_row, self.user_row, self.domain_row):
            row.connect("changed", lambda *_a: self._update())
        self._on_protocol()
        self.set_focus(self.host_row if not editing else self.name_row)

    def _scheme_info(self):
        return PROTOCOLS[self.protocol_row.get_selected()]

    def _on_port(self, *_args):
        if not self._setting_port:
            self._port_is_default = int(self.port_row.get_value()) == self._scheme_info()[2]
        self._update()

    _setting_port = False

    def _on_protocol(self):
        info = self._scheme_info()
        if self._port_is_default:
            self._setting_port = True
            self.port_row.set_value(info[2])
            self._setting_port = False
        self.domain_row.set_visible(info[0] == "smb")
        self._update()

    def _fields(self):
        info = self._scheme_info()
        port = int(self.port_row.get_value())
        return {**self.server, "name": self.name_row.get_text().strip(), "protocol": info[0],
                "host": self.host_row.get_text().strip(), "port": 0 if port == info[2] else port,
                "path": self.path_row.get_text().strip().strip("/"), "user": self.user_row.get_text().strip(),
                "domain": self.domain_row.get_text().strip() if info[0] == "smb" else ""}

    def _update(self):
        fields = self._fields()
        ok = bool(fields["host"]) and " " not in fields["host"]
        self.save_button.set_sensitive(ok)
        self.address.set_description(_("Address: {uri}").format(uri=GLib.markup_escape_text(build_uri(fields)))
                                     if ok else None)

    def _save(self):
        server = save_server(self.window.settings, self._fields())
        if not set_password(server["id"], self.password_row.get_text(), server["name"]) and \
                self.password_row.get_text():
            self.window.toast(_("The password could not be saved in the keyring."))
        self.close()
        if self.on_saved:
            self.on_saved(server)

    def _delete(self):
        remove_server(self.window.settings, self.server.get("uri", ""))
        self.close()
        if self.on_saved:
            self.on_saved(None)


# --------------------------------------------------------------- server hub

class ConnectDialog(Adw.Dialog):
    """The server manager: quick connect, saved servers, recent addresses."""

    def __init__(self, window):
        super().__init__(title=_("Servers"), content_width=600, content_height=640)
        self.window = window
        self.settings = window.settings
        self.lock_button = Gtk.Button(icon_name="system-lock-screen-symbolic", tooltip_text=_("Lock Servers"))
        self.lock_button.connect("clicked", lambda *_a: (_vault(self.settings).lock(), self._fill_lists()))

        self.entry = Adw.EntryRow(title=_("Quick Connect — address"))
        self.entry.connect("entry-activated", lambda *_a: self._quick_connect())
        go = Gtk.Button(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                        tooltip_text=_("Connect"))
        go.connect("clicked", lambda *_a: self._quick_connect())
        save = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text=_("Save as a Server…"))
        save.connect("clicked", lambda *_a: self._save_address())
        self.entry.add_suffix(save)
        self.entry.add_suffix(go)
        examples = _("Examples: {examples}").format(examples=" · ".join((
            "smb://nas.local/share", "sftp://user@server.com", "ftp://ftp.example.com",
            "davs://cloud.example.com/remote.php/webdav")))
        quick = Adw.PreferencesGroup(description=examples)
        quick.add(self.entry)

        self.search = Gtk.SearchEntry(placeholder_text=_("Search servers"), hexpand=True)
        self.search.connect("search-changed", lambda *_a: self._filter())
        self.search_group = Adw.PreferencesGroup()
        self.search_group.add(self.search)

        self.page = Adw.PreferencesPage()
        self.page.add(quick)
        self.page.add(self.search_group)
        self.lists = []
        self.rows = []
        self._fill_lists()

        header = Adw.HeaderBar()
        header.pack_start(self.lock_button)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(self.page)
        self.set_child(toolbar)
        self.set_focus(self.entry if not saved_servers(self.settings) else self.search)

    # ---------------------------------------------------------------- lists

    def _fill_lists(self):
        for group in self.lists:
            self.page.remove(group)
        self.lists = []
        self.rows = []
        vault = _vault(self.settings)
        self.lock_button.set_visible(vault.uses_master and not vault.locked)
        if vault.locked:
            self.search_group.set_visible(False)
            self.lists.append(self._unlock_group(vault))
            self.page.add(self.lists[0])
            return
        servers = saved_servers(self.settings)
        self.search_group.set_visible(len(servers) > 4)

        mine = Adw.PreferencesGroup(title=_("My Servers"))
        new = Gtk.Button(label=_("New Server"), css_classes=["flat"], valign=Gtk.Align.CENTER)
        new.connect("clicked", lambda *_a: self._edit(None))
        mine.set_header_suffix(new)
        if not servers:
            mine.set_description(_("Save your servers with their login to connect in one click. They also "
                                   "appear in the sidebar."))
        for server in servers:
            haystack = " ".join((server["name"], server.get("host", ""), server.get("user", ""),
                                 server["protocol"])).lower()
            row = self._server_row(server)
            self.rows.append((row, haystack))
            mine.add(row)
        self.lists.append(mine)

        recent_uris = [u for u in recent_servers(self.settings) if not any(s["uri"] == u for s in servers)]
        if recent_uris:
            recent = Adw.PreferencesGroup(title=_("Recent Servers"))
            for uri in recent_uris:
                row = Adw.ActionRow(title=GLib.markup_escape_text(server_name(uri)),
                                    subtitle=GLib.markup_escape_text(uri), activatable=True)
                row.add_prefix(Gtk.Image(icon_name="document-open-recent-symbolic"))
                keep = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                  tooltip_text=_("Save as a Server…"))
                keep.connect("clicked", lambda _b, u=uri: self._edit(parse_uri(u)))
                row.add_suffix(keep)
                row.connect("activated", lambda _r, u=uri: self._open(u))
                recent.add(row)
            self.lists.append(recent)
        for group in self.lists:
            self.page.add(group)
        self._filter()

    def _unlock_group(self, vault):
        if vault.uses_master:
            group = Adw.PreferencesGroup(
                title=_("Servers Locked"),
                description=_("Your server list is encrypted. Type your master password to open it."))
            row = Adw.PasswordEntryRow(title=_("Master Password"))
            unlock = Gtk.Button(label=_("Unlock"), valign=Gtk.Align.CENTER, css_classes=["suggested-action"])

            def try_unlock(*_args):
                if vault.unlock(row.get_text()):
                    self._fill_lists()
                else:
                    row.set_text("")
                    row.add_css_class("error")
                    group.set_description(_("Wrong master password."))

            row.connect("entry-activated", try_unlock)
            unlock.connect("clicked", try_unlock)
            row.add_suffix(unlock)
            group.add(row)
            GLib.idle_add(lambda: row.grab_focus() and False)
        else:
            group = Adw.PreferencesGroup(
                title=_("Servers Unavailable"),
                description=_("The encrypted server list could not be opened: the GNOME keyring is not "
                              "available or its key is missing."))
        return group

    def _filter(self):
        needle = self.search.get_text().strip().lower()
        for row, haystack in self.rows:
            row.set_visible(not needle or needle in haystack)

    def _server_row(self, server):
        row = Adw.ActionRow(title=GLib.markup_escape_text(server["name"]),
                            subtitle=GLib.markup_escape_text(describe(server)), activatable=True)
        icon = Gtk.Image(icon_name=protocol_info(server["protocol"])[3], css_classes=["galet-server-icon"])
        row.add_prefix(icon)
        if find_mount(Gio.File.new_for_uri(server["uri"])) is not None:
            row.add_suffix(Gtk.Image(icon_name="emblem-ok-symbolic", tooltip_text=_("Connected"),
                                     css_classes=["success"]))
        if server["protocol"] == "sftp":
            ssh = Gtk.Button(icon_name="utilities-terminal-symbolic", valign=Gtk.Align.CENTER,
                             css_classes=["flat"], tooltip_text=_("Open SSH Terminal"))
            ssh.connect("clicked", lambda *_a: (self.close(), open_ssh(self.window, server)))
            row.add_suffix(ssh)
        transfer = Gtk.Button(icon_name="view-dual-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                              tooltip_text=_("Transfer Files (dual pane)"))
        transfer.connect("clicked", lambda *_a: (self.close(), self.window.open_transfer(server["uri"])))
        row.add_suffix(transfer)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                          tooltip_text=_("Edit Server…"))
        edit.connect("clicked", lambda *_a: self._edit(server))
        row.add_suffix(edit)
        more = Gtk.MenuButton(icon_name="view-more-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                              tooltip_text=_("More"))
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for label, callback in ((_("Copy Address"), lambda: self._copy(server["uri"])),
                                (_("Duplicate"), lambda: self._duplicate(server)),
                                (_("Delete Server"), lambda: self._delete(server))):
            button = Gtk.Button(label=label, css_classes=["flat"])
            button.get_child().set_xalign(0)
            button.connect("clicked", lambda _b, cb=callback: (popover.popdown(), cb()))
            box.append(button)
        popover.set_child(box)
        more.set_popover(popover)
        row.add_suffix(more)
        row.connect("activated", lambda _r: self._open(server["uri"]))
        return row

    # -------------------------------------------------------------- actions

    def _address(self):
        text = self.entry.get_text().strip()
        return normalize_address(text) if text else None

    def _quick_connect(self):
        uri = self._address()
        if uri:
            self._open(uri)

    def _save_address(self):
        uri = self._address()
        self._edit(parse_uri(uri) if uri else None)

    def _open(self, uri):
        remember_recent(self.settings, uri)
        self.close()
        self.window.open_server(Gio.File.new_for_uri(uri))

    def _edit(self, server):
        ServerEditor(self.window, server, on_saved=lambda _s: self._fill_lists()).present(self)

    def _copy(self, uri):
        Gdk.Display.get_default().get_clipboard().set(uri)
        self.window.toast(_("Address copied"))

    def _duplicate(self, server):
        copy = {k: v for k, v in server.items() if k not in ("id", "uri")}
        copy["name"] = _("{name} (copy)").format(name=server["name"])
        save_server(self.settings, copy)
        self._fill_lists()

    def _delete(self, server):
        dialog = Adw.AlertDialog(heading=_("Delete “{name}”?").format(name=server["name"]),
                                 body=_("The server and its saved password are removed. Your files on the "
                                        "server are not touched."))
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("delete", _("Delete"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, r: r == "delete" and (remove_server(self.settings, server["uri"]),
                                                                     self._fill_lists()))
        dialog.present(self)
