"""The org.freedesktop.FileManager1 D-Bus service.

Applications such as VS Code ("Reveal in File Explorer"), web browsers ("Show in
folder") and download managers don't use the default file manager setting: they
call this D-Bus interface. When Galet owns the name, they open Galet.
"""

from gi.repository import Gio, GLib

from .logs import log
from .model import Location

BUS_NAME = "org.freedesktop.FileManager1"
OBJECT_PATH = "/org/freedesktop/FileManager1"
INTERFACE_XML = """
<node>
  <interface name="org.freedesktop.FileManager1">
    <method name="ShowFolders">
      <arg type="as" name="URIs" direction="in"/>
      <arg type="s" name="StartupId" direction="in"/>
    </method>
    <method name="ShowItems">
      <arg type="as" name="URIs" direction="in"/>
      <arg type="s" name="StartupId" direction="in"/>
    </method>
    <method name="ShowItemProperties">
      <arg type="as" name="URIs" direction="in"/>
      <arg type="s" name="StartupId" direction="in"/>
    </method>
  </interface>
</node>
"""


class FileManagerService:
    def __init__(self, app):
        self.app = app
        self._registration = 0
        self._owner = 0

    def start(self):
        connection = self.app.get_dbus_connection()
        if connection is None:
            return
        info = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML).interfaces[0]
        try:
            self._registration = connection.register_object(OBJECT_PATH, info, self._on_call, None, None)
        except GLib.Error as err:
            log.warning("FileManager1: cannot register object: %s", err.message)
            return
        # Take the name over from GNOME Files when possible, and let it back if Galet quits.
        flags = Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT
        self._owner = Gio.bus_own_name_on_connection(connection, BUS_NAME, flags,
                                                     lambda *_a: log.info("FileManager1 name acquired"),
                                                     lambda *_a: log.info("FileManager1 name not owned"))

    def stop(self):
        if self._owner:
            Gio.bus_unown_name(self._owner)
            self._owner = 0
        connection = self.app.get_dbus_connection()
        if connection is not None and self._registration:
            connection.unregister_object(self._registration)
            self._registration = 0

    # ---------------------------------------------------------------- calls

    def _on_call(self, _connection, _sender, _path, _interface, method, parameters, invocation):
        uris, startup_id = parameters.unpack()
        files = [Gio.File.new_for_uri(uri) if "://" in uri else Gio.File.new_for_path(uri) for uri in uris]
        handlers = {"ShowFolders": self._show_folders, "ShowItems": self._show_items,
                    "ShowItemProperties": self._show_properties}
        handler = handlers.get(method)
        if handler is None:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)
            return
        invocation.return_value(None)
        GLib.idle_add(lambda: handler(files, startup_id) and False)

    def _window(self, startup_id):
        window = self.app.get_active_window()
        if window is None:
            window = self.app.new_window(empty=True)
        if startup_id:
            window.set_startup_id(startup_id)
        window.present()
        return window

    def _open(self, folder, startup_id):
        window = self._window(startup_id)
        if window.tab_view.get_n_pages() and self.app.settings.get("open_in_tabs"):
            window.new_tab(Location(folder))
        elif window.tab_view.get_n_pages():
            window = self.app.new_window(Location(folder))
            if startup_id:
                window.set_startup_id(startup_id)
            window.present()
        else:
            window.new_tab(Location(folder))
        return window

    def _show_folders(self, files, startup_id):
        for folder in files:
            self._open(folder, startup_id)

    def _show_items(self, files, startup_id, then=None):
        by_parent = {}
        for gfile in files:
            parent = gfile.get_parent() or gfile
            by_parent.setdefault(parent.get_uri(), (parent, []))[1].append(gfile)
        for parent, items in by_parent.values():
            window = self._open(parent, startup_id)
            pane = window.current_pane
            pane.reveal(items[0], rename=False)
            if then is not None:
                GLib.timeout_add(600, lambda w=window: then(w) and False)

    def _show_properties(self, files, startup_id):
        self._show_items(files, startup_id, then=lambda window: window.activate_action("win.get-info", None))
