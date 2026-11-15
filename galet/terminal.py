"""Built-in terminal panel (bottom of the window, like an IDE).

Each tab is a VTE terminal. A local terminal opens in the current folder with your
own shell; on an SFTP server it opens an SSH session in the same folder. Inside the
Flatpak, the shell runs on the host system (flatpak-spawn --host), so all your
programs are there.

VTE is bundled in the Flatpak. Outside it, install gir1.2-vte-3.91 (Debian, Ubuntu,
Zorin) or vte4 (Fedora, Arch); without it the panel offers the system terminal.
"""

import os
import shlex

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from .i18n import _
from .sandbox import IN_FLATPAK

try:
    import gi

    gi.require_version("Vte", "3.91")
    from gi.repository import Vte
except (ImportError, ValueError):
    Vte = None

# Galet palette (readable on light and dark backgrounds)
PALETTE_DARK = ("#1e1e24", "#e5534b", "#57ab5a", "#c69026", "#539bf5", "#b083f0", "#39c5cf", "#d1d7e0",
                "#5c6370", "#ff7b72", "#7ee787", "#e3b341", "#79c0ff", "#d2a8ff", "#56d4dd", "#ffffff")
PALETTE_LIGHT = ("#24292f", "#cf222e", "#116329", "#9a6700", "#0550ae", "#8250df", "#1b7c83", "#6e7781",
                 "#57606a", "#a40e26", "#1a7f37", "#7d4e00", "#0969da", "#a475f9", "#3192aa", "#8c959f")


def available():
    return Vte is not None


def _rgba(text):
    color = Gdk.RGBA()
    color.parse(text)
    return color


def _host_shell_argv(directory):
    """argv for the user's login shell in ``directory``."""
    if IN_FLATPAK:
        script = 'exec "$(getent passwd "$(id -un)" | cut -d: -f7)" -l'
        return ["flatpak-spawn", "--host", "--watch-bus", f"--directory={directory}",
                "--env=TERM=xterm-256color", "--env=COLORTERM=truecolor", "sh", "-c", script]
    shell = Vte.get_user_shell() or os.environ.get("SHELL") or "/bin/bash"
    return [shell, "-l"]


def _ssh_argv(server, path):
    args = ["ssh", "-t"]
    port = int(server.get("port") or 0)
    if port and port != 22:
        args += ["-p", str(port)]
    args.append((f"{server['user']}@" if server.get("user") else "") + server["host"])
    if path:
        args.append(f"cd {shlex.quote(path)} 2>/dev/null; exec \"$SHELL\" -l")
    if IN_FLATPAK:  # the host's ssh: your ~/.ssh/config, agent and known hosts
        return ["flatpak-spawn", "--host", "--watch-bus", "--env=TERM=xterm-256color", *args]
    return args


class _Terminal(Gtk.Box):
    """One terminal tab."""

    def __init__(self, panel, argv, directory, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.panel = panel
        self.title = title
        self.directory = directory
        self.term = Vte.Terminal(hexpand=True, vexpand=True, scrollback_lines=10000,
                                 allow_hyperlink=True, pointer_autohide=True)
        self.term._galet_terminal = True
        self.term.set_font(Pango.FontDescription.from_string(panel.window.settings.get("terminal_font",
                                                                                         "Monospace 11")))
        scroller = Gtk.ScrolledWindow(child=self.term, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.append(scroller)
        self.term.connect("child-exited", self._on_exited)
        self.term.connect("notify::window-title", lambda *_a: panel.update_title(self))
        self.apply_colors()

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.term.add_controller(keys)

        cwd = directory if directory and os.path.isdir(directory) else GLib.get_home_dir()
        env = [f"{k}={v}" for k, v in os.environ.items()] + ["TERM=xterm-256color", "COLORTERM=truecolor"]
        # In the Flatpak the shell runs on the host: flatpak-spawn must not own the terminal, so that
        # the host shell can make it its controlling terminal (Ctrl+C, job control, resizing).
        flags = Vte.PtyFlags.NO_CTTY if argv[0] == "flatpak-spawn" else Vte.PtyFlags.DEFAULT
        self.term.spawn_async(flags, cwd, argv, env, GLib.SpawnFlags.SEARCH_PATH,
                              None, None, -1, None, self._on_spawned)

    def _on_spawned(self, _terminal, pid, error, *_args):
        if error is not None:
            self.term.feed(("\r\n" + _("Could not start the terminal: {error}").format(error=error.message)
                            + "\r\n").encode("utf-8"))

    def apply_colors(self):
        dark = Adw.StyleManager.get_default().get_dark()
        palette = PALETTE_DARK if dark else PALETTE_LIGHT
        fg, bg = ("#e6e6eb", "#1e1e24") if dark else ("#24292f", "#fafafa")
        self.term.set_colors(_rgba(fg), _rgba(bg), [_rgba(c) for c in palette])

    def _on_key(self, _controller, keyval, _code, state):
        ctrl_shift = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        if state & ctrl_shift == ctrl_shift:
            if keyval in (Gdk.KEY_C, Gdk.KEY_c):
                self.term.copy_clipboard_format(Vte.Format.TEXT)
                return True
            if keyval in (Gdk.KEY_V, Gdk.KEY_v):
                self.term.paste_clipboard()
                return True
        return False

    def _on_exited(self, *_args):
        self.panel.close_terminal(self)

    def send(self, text):
        self.term.feed_child(text.encode("utf-8"))

    def grab_focus(self):
        return self.term.grab_focus()


class TerminalPanel(Gtk.Box):
    """Terminal tabs shown under the files."""

    def __init__(self, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, css_classes=["galet-terminal-panel"])
        self.window = window

        self.view = Adw.TabView()
        self.view.connect("close-page", self._on_close_page)
        self.view.connect("notify::selected-page", lambda *_a: self._focus_current())
        bar = Adw.TabBar(view=self.view, autohide=False, hexpand=True)
        header = Gtk.Box(css_classes=["galet-terminal-header"])
        header.append(bar)
        buttons = Gtk.Box(spacing=2, margin_start=4, margin_end=4, valign=Gtk.Align.CENTER)
        for icon, tooltip, callback in (
                ("tab-new-symbolic", _("New Terminal"), lambda: self.new_terminal()),
                ("folder-symbolic", _("Go to the Current Folder"), self.cd_to_current),
                ("window-close-symbolic", _("Hide Terminal"), lambda: window.show_terminal(False))):
            button = Gtk.Button(icon_name=icon, tooltip_text=tooltip, css_classes=["flat", "circular"])
            button.connect("clicked", lambda _b, cb=callback: cb())
            buttons.append(button)
        header.append(buttons)
        self.append(header)

        if Vte is None:
            status = Adw.StatusPage(icon_name="utilities-terminal-symbolic", title=_("Terminal Unavailable"),
                                    description=_("The built-in terminal needs VTE: install the package "
                                                  "gir1.2-vte-3.91 (Ubuntu, Zorin, Debian) or vte4 (Fedora, "
                                                  "Arch), or use the Flatpak version of Galet."),
                                    vexpand=True)
            system = Gtk.Button(label=_("Open the System Terminal"), halign=Gtk.Align.CENTER,
                                css_classes=["pill", "suggested-action"])
            system.connect("clicked", lambda *_a: window.activate_action("win.open-terminal", None))
            status.set_child(system)
            self.append(status)
            bar.set_visible(False)
            buttons.get_first_child().set_visible(False)
            buttons.get_first_child().get_next_sibling().set_visible(False)
        else:
            self.append(self.view)
            Adw.StyleManager.get_default().connect("notify::dark", lambda *_a: self._recolor())

    # ------------------------------------------------------------ terminals

    def _current_target(self):
        """(argv, directory, title) for the folder shown in the current tab."""
        from . import servers

        pane = self.window.current_pane
        location = pane.location if pane is not None else None
        gfile = location.gfile if location is not None and not location.is_virtual else None
        if gfile is not None and gfile.get_uri_scheme() in ("sftp", "ssh"):
            fields = servers.parse_uri(gfile.get_uri())
            saved = servers.server_for(self.window.settings, gfile)
            server = dict(fields)
            if saved:
                server.update({k: saved[k] for k in ("user", "port") if saved.get(k)})
            path = "/" + fields["path"] if fields["path"] else ""
            name = saved["name"] if saved else fields["host"]
            return _ssh_argv(server, path), None, name
        directory = gfile.get_path() if gfile is not None else None
        directory = directory or GLib.get_home_dir()
        return _host_shell_argv(directory), directory, os.path.basename(directory.rstrip("/")) or "/"

    def new_terminal(self, argv=None, directory=None, title=None):
        if Vte is None:
            return None
        if argv is None:
            argv, directory, title = self._current_target()
        terminal = _Terminal(self, argv, directory, title)
        page = self.view.append(terminal)
        page.set_title(title or _("Terminal"))
        page.set_icon(Gio.ThemedIcon.new("utilities-terminal-symbolic"))
        self.view.set_selected_page(page)
        GLib.idle_add(lambda: terminal.grab_focus() and False)
        return terminal

    def open_ssh(self, server):
        return self.new_terminal(_ssh_argv(server, "/" + server["path"] if server.get("path") else ""),
                                 None, server["name"])

    def ensure_terminal(self):
        if Vte is not None and self.view.get_n_pages() == 0:
            self.new_terminal()
        else:
            self._focus_current()

    def current(self):
        page = self.view.get_selected_page()
        return page.get_child() if page is not None else None

    def cd_to_current(self):
        terminal = self.current()
        pane = self.window.current_pane
        if terminal is None or pane is None or pane.location.is_virtual:
            return
        path = pane.location.gfile.get_path()
        if path and terminal.directory is not None:  # local terminals only
            terminal.send(f" cd {shlex.quote(path)}\n")
            terminal.grab_focus()

    def close_terminal(self, terminal):
        page = self.view.get_page(terminal)
        if page is not None:
            self.view.close_page(page)

    def _on_close_page(self, view, page):
        view.close_page_finish(page, True)
        # the last terminal closed (e.g. "exit"): hide the panel
        GLib.idle_add(lambda: (view.get_n_pages() == 0 and self.window.show_terminal(False)) and False)
        return Gdk.EVENT_STOP

    def update_title(self, terminal):
        page = self.view.get_page(terminal)
        title = terminal.term.get_window_title() if hasattr(terminal.term, "get_window_title") else None
        if page is not None and title:
            page.set_tooltip(title)

    def _focus_current(self):
        terminal = self.current()
        if terminal is not None:
            GLib.idle_add(lambda: terminal.grab_focus() and False)

    def _recolor(self):
        for i in range(self.view.get_n_pages()):
            self.view.get_nth_page(i).get_child().apply_colors()

