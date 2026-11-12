"""Application entry point, settings and keyboard shortcuts."""

import json
import os
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk

from . import APP_ID, __version__
from .i18n import _
from .model import Location
from .tags import TagStore

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

ACCELS = {
    "win.back": ["<Alt>Left", "<Control>bracketleft"],
    "win.forward": ["<Alt>Right", "<Control>bracketright"],
    "win.up": ["<Alt>Up", "<Control>Up"],
    "win.open": ["<Control>Down", "<Control>o"],
    "win.new-tab": ["<Control>t"],
    "win.close-tab": ["<Control>w"],
    "win.view-mode::grid": ["<Control>1"],
    "win.view-mode::list": ["<Control>2"],
    "win.view-mode::columns": ["<Control>3"],
    "win.view-mode::gallery": ["<Control>4"],
    "win.get-info": ["<Control>i"],
    "win.show-preview": ["<Control><Shift>p"],
    "win.show-hidden": ["<Control>h", "<Control><Shift>period"],
    "win.search": ["<Control>f"],
    "win.go-to": ["<Control>l", "<Control><Shift>g"],
    "win.new-folder": ["<Control><Shift>n"],
    "win.reload": ["F5", "<Control>r"],
    "win.edit-tags": ["<Control><Alt>t"],
    "app.new-window": ["<Control>n"],
    "app.quit": ["<Control>q"],
    "app.preferences": ["<Control>comma"],
    "win.connect-server": ["<Control>k"],
    "win.new-folder-with-selection": ["<Control><Alt>n"],
    "win.go-home": ["<Control><Shift>h"],
    "win.go-desktop": ["<Control><Shift>d"],
    "win.go-documents": ["<Control><Shift>o"],
    "win.go-downloads": ["<Control><Alt>l"],
    "win.go-recent": ["<Control><Shift>f"],
    "win.go-network": ["<Control><Shift>k"],
}


SIDEBAR_ITEMS = ("recent", "home", "desktop", "documents", "downloads", "pictures", "music",
                 "videos", "bookmarks", "computer", "mounts", "network", "servers", "trash", "tags")

DEFAULTS = {
    "view_mode": "grid",
    "show_hidden": False,
    "window_size": [1100, 700],
    "new_window_location": "home",
    "open_in_tabs": True,
    "icon_size": 64,
    "folders_first": True,
    "show_extensions": True,
    "show_bottom_bar": True,
    "sidebar": {name: True for name in SIDEBAR_ITEMS},
    "servers": [],
    "show_preview": False,
    "smart_folders": [],
    "theme": "system",
    "color_scheme": "auto",
    "sort_by": "name",
    "folder_views": {},
    "group_by": "none",
    "recent_servers": [],
}


class Settings(GObject.Object):
    """JSON-backed settings (~/.config/galet/settings.json).

    Emits ``changed(key)`` so every window can apply a new value live.
    """

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self):
        super().__init__()
        self.path = Path(GLib.get_user_config_dir()) / "galet" / "settings.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                self.data = {}
        except (OSError, ValueError):
            self.data = {}

    def get(self, key, default=None):
        if key in self.data:
            return self.data[key]
        return DEFAULTS.get(key, default)

    def set(self, key, value):
        if self.data.get(key) == value:
            return
        self.data[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as err:
            print(f"galet: cannot save settings: {err}")
        self.emit("changed", key)

    def sidebar_shows(self, item):
        return bool(self.get("sidebar", {}).get(item, True))

    def set_sidebar(self, item, visible):
        sidebar = dict(DEFAULTS["sidebar"])
        sidebar.update(self.get("sidebar", {}))
        sidebar[item] = visible
        self.set("sidebar", sidebar)


class GaletApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
        self.tagstore = None
        self.settings = None
        self.clipboard_files = None
        self.undo_stack = []

    def do_startup(self):
        Adw.Application.do_startup(self)
        GLib.set_application_name("Galet")
        from . import logs

        logs.setup(__version__)
        self.tagstore = TagStore()
        self.settings = Settings()
        from . import phone

        phone.phones()  # start watching paired phones early

        display = Gdk.Display.get_default()
        Gtk.IconTheme.get_for_display(display).add_search_path(str(DATA_DIR / "icons"))
        from .themes import ThemeManager

        self.themes = ThemeManager(self.settings)
        css = Gtk.CssProvider()
        css.load_from_path(str(Path(__file__).resolve().parent / "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        for name, callback in (("new-window", lambda *_a: self._new_window()),
                               ("about", self._on_about),
                               ("preferences", self._on_preferences),
                               ("quit", lambda *_a: self.quit())):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            self.add_action(action)
        for action, accels in ACCELS.items():
            self.set_accels_for_action(action, accels)

    def do_activate(self):
        self._new_window()

    def do_open(self, files, _n_files, _hint):
        window = self.get_active_window()
        for gfile in files:
            if gfile.query_file_type(Gio.FileQueryInfoFlags.NONE, None) != Gio.FileType.DIRECTORY:
                gfile = gfile.get_parent() or gfile
            if window is not None and self.settings.get("open_in_tabs"):
                window.new_tab(Location(gfile))
                window.present()
            else:
                window = self._new_window(Location(gfile))

    def do_shutdown(self):
        if self.tagstore is not None:
            self.tagstore.flush()
        Adw.Application.do_shutdown(self)

    def _new_window(self, location=None):
        from .window import GaletWindow

        window = GaletWindow(self, location)
        window.present()
        return window

    def _on_preferences(self, *_args):
        from .preferences import PreferencesDialog

        PreferencesDialog(self).present(self.get_active_window())

    def _on_about(self, *_args):
        about = Adw.AboutDialog(
            application_name="Galet",
            application_icon="system-file-manager",
            version=__version__,
            comments=_("A Finder-inspired file manager with tabs, columns and colour tags."),
            license_type=Gtk.License.GPL_3_0,
            developers=["Florian Dérail"],
            website="https://github.com/FloDerail/galet",
            issue_url="https://github.com/FloDerail/galet/issues",
        )
        about.present(self.get_active_window())
