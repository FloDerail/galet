"""Send files to a phone, AirDrop-style, through Zorin Connect / GSConnect.

Both services expose paired devices over D-Bus with a "shareFile" action, the
same interface the GNOME Files extension uses.
"""

from gi.repository import Gio, GLib

SERVICES = (
    ("org.gnome.Shell.Extensions.ZorinConnect", "/org/gnome/Shell/Extensions/ZorinConnect",
     "org.gnome.Shell.Extensions.ZorinConnect.Device"),
    ("org.gnome.Shell.Extensions.GSConnect", "/org/gnome/Shell/Extensions/GSConnect",
     "org.gnome.Shell.Extensions.GSConnect.Device"),
)


class Phones:
    """Keeps an up-to-date list of paired devices."""

    def __init__(self):
        self.devices = {}  # object path -> {"name", "connected", "actions"}
        self._proxies = []
        for name, path, interface in SERVICES:
            Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_AUTO_START, None,
                                      name, path, "org.freedesktop.DBus.ObjectManager", None,
                                      self._on_proxy, (name, interface))

    def _on_proxy(self, _source, result, data):
        try:
            proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error:
            return
        self._proxies.append(proxy)
        service, interface = data
        proxy.connect("g-signal", lambda p, _s, signal, params: self._refresh(p, service, interface))
        proxy.connect("notify::g-name-owner", lambda p, _ps: self._refresh(p, service, interface))
        self._refresh(proxy, service, interface)

    def _refresh(self, proxy, service, interface):
        for path in [p for p, d in self.devices.items() if d["service"] == service]:
            del self.devices[path]
        if proxy.get_name_owner() is None:
            return

        def done(source, result, *_args):
            try:
                objects = source.call_finish(result).unpack()[0]
            except GLib.Error:
                return
            for path, interfaces in objects.items():
                props = interfaces.get(interface)
                if not props or not props.get("Paired", True):
                    continue
                actions = Gio.DBusActionGroup.get(source.get_connection(), service, path)
                actions.list_actions()  # starts loading the action list
                self.devices[path] = {"name": props.get("Name", "?"), "connected": props.get("Connected", False),
                                      "icon": props.get("IconName", "phone-symbolic"), "actions": actions,
                                      "service": service}

        proxy.call("GetManagedObjects", None, Gio.DBusCallFlags.NO_AUTO_START, -1, None, done)

    def available(self):
        """[(object_path, name)] of devices that can receive files right now."""
        result = []
        for path, device in self.devices.items():
            actions = device["actions"]
            if actions.has_action("shareFile") and actions.get_action_enabled("shareFile"):
                result.append((path, device["name"]))
        return result

    def send(self, path, uris):
        device = self.devices.get(path)
        if device is None:
            return False
        for uri in uris:
            device["actions"].activate_action("shareFile", GLib.Variant("(sb)", (uri, False)))
        return True


PHONES = None


def phones():
    global PHONES
    if PHONES is None:
        PHONES = Phones()
    return PHONES
