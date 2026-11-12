"""Appearance themes: System, macOS, Windows 11 and Custom.

A theme is a small set of values (accent colour, sidebar/content colours,
corner radius, font, window-button style and side) turned into a CSS layer on
top of libadwaita. Light and dark variants are regenerated when the system
switches between them.
"""

from gi.repository import Adw, Gdk, Gtk

from .i18n import N_

THEMES = {
    "system": {"label": N_("System")},
    "macos": {
        "label": "macOS",
        "accent": "#007aff",
        "light": {"content": "#ffffff", "sidebar": "#ecebee", "header": "#f6f5f7", "line": "#d9d8db",
                  "fg": "#1d1d1f", "dim": "#86868b"},
        "dark": {"content": "#1e1e1e", "sidebar": "#2b2a2c", "header": "#2a292b", "line": "#3a393b",
                 "fg": "#f5f5f7", "dim": "#98989d"},
        "radius": 7,
        "font": "Inter",
        "controls": "left",
        "buttons": "traffic",
        "selection": "mac",
    },
    "windows": {
        "label": "Windows 11",
        "accent": "#0067c0",
        "light": {"content": "#ffffff", "sidebar": "#f3f3f3", "header": "#f3f3f3", "line": "#e5e5e5",
                  "fg": "#1a1a1a", "dim": "#5f5f5f"},
        "dark": {"content": "#191919", "sidebar": "#202020", "header": "#202020", "line": "#2d2d2d",
                 "fg": "#ffffff", "dim": "#a0a0a0"},
        "radius": 4,
        "font": "Noto Sans",
        "controls": "right",
        "buttons": "windows",
        "selection": "windows",
    },
    "custom": {"label": N_("Custom")},
}

THEME_ORDER = ("system", "macos", "windows", "custom")
COLOR_SCHEMES = (("auto", N_("Follow System")), ("light", N_("Light")), ("dark", N_("Dark")))
CONTROL_SIDES = (("system", N_("System")), ("left", N_("Left")), ("right", N_("Right")))
BUTTON_STYLES = (("system", N_("System")), ("traffic", N_("Coloured dots (macOS)")),
                 ("windows", N_("Rectangles (Windows)")))

CUSTOM_DEFAULTS = {
    "custom_accent": "#8e44ad",
    "custom_controls": "system",
    "custom_buttons": "system",
    "custom_radius": 10,
    "custom_font": "",
    "custom_sidebar_tint": True,
}

LAYOUTS = {"left": "close,minimize,maximize:", "right": ":minimize,maximize,close"}


def _mix(color_a, color_b, amount):
    a, b = Gdk.RGBA(), Gdk.RGBA()
    a.parse(color_a)
    b.parse(color_b)
    mix = [a.red * (1 - amount) + b.red * amount, a.green * (1 - amount) + b.green * amount,
           a.blue * (1 - amount) + b.blue * amount]
    return "#" + "".join(f"{round(c * 255):02x}" for c in mix)


def resolve(settings, dark):
    """The effective values of the selected theme (None for the System theme)."""
    name = settings.get("theme", "system")
    if name == "custom":
        get = lambda key: settings.get(key, CUSTOM_DEFAULTS[key])  # noqa: E731
        accent = get("custom_accent")
        base = THEMES["windows"]["dark" if dark else "light"]
        tint = 0.10 if get("custom_sidebar_tint") else 0.0
        return {
            "accent": accent,
            "content": base["content"],
            "sidebar": _mix(base["sidebar"], accent, tint),
            "header": _mix(base["header"], accent, tint / 2),
            "line": base["line"],
            "fg": base["fg"],
            "dim": base["dim"],
            "radius": int(get("custom_radius")),
            "font": get("custom_font"),
            "controls": get("custom_controls"),
            "buttons": get("custom_buttons"),
            "selection": "default",
        }
    theme = THEMES.get(name)
    if theme is None or "accent" not in theme:
        return None
    values = dict(theme)
    values.update(theme["dark" if dark else "light"])
    return values


def build_css(values):
    if values is None:
        return ""
    radius = values["radius"]
    v = values
    # Explicit colours (not only @define-color): distributions such as Zorin OS
    # restyle libadwaita, so every surface and its text colour is set here.
    css = [f"""
@define-color accent_bg_color {v['accent']};
@define-color accent_color {v['accent']};
@define-color accent_fg_color #ffffff;
@define-color window_bg_color {v['content']};
@define-color window_fg_color {v['fg']};
@define-color view_bg_color {v['content']};
@define-color view_fg_color {v['fg']};
@define-color headerbar_bg_color {v['header']};
@define-color headerbar_fg_color {v['fg']};
@define-color headerbar_backdrop_color {v['header']};
@define-color sidebar_bg_color {v['sidebar']};
@define-color sidebar_fg_color {v['fg']};
@define-color sidebar_backdrop_color {v['sidebar']};
@define-color headerbar_shade_color {v['line']};

window.galet-window,
.galet-window .view,
.galet-window gridview,
.galet-window columnview,
.galet-window columnview > listview,
.galet-window listview,
.galet-window scrolledwindow,
.galet-window .galet-info-panel,
.galet-window statuspage {{ background-color: {v['content']}; color: {v['fg']}; }}

.galet-window headerbar,
.galet-window tabbar,
.galet-window tabbar > revealer > box,
.galet-window searchbar,
.galet-window searchbar > revealer > box,
.galet-window .galet-bottombar {{ background-color: {v['header']}; color: {v['fg']};
  box-shadow: none; border-color: {v['line']}; }}

.galet-window .sidebar-pane,
.galet-window .sidebar-pane headerbar,
.galet-window .sidebar-pane scrolledwindow,
.galet-window .navigation-sidebar {{ background-color: {v['sidebar']}; color: {v['fg']}; }}

.galet-window label {{ color: inherit; }}
.galet-window .dim-label,
.galet-window .sidebar-heading,
.galet-window columnview > header > button {{ color: {v['dim']}; opacity: 1; }}
.galet-window separator {{ background-color: {v['line']}; }}
.galet-window headerbar button:not(.suggested-action):not(.destructive-action) {{ color: {v['fg']}; }}
.galet-window entry, .galet-window searchbar entry {{ background-color: alpha({v['fg']}, 0.07);
  color: {v['fg']}; }}

window.galet-window .navigation-sidebar > row:selected,
window.galet-window .navigation-sidebar > row:selected:hover,
window.galet-window .navigation-sidebar > row:selected:focus {{ background: {v['accent']}; color: #ffffff; }}
window.galet-window gridview > child:selected,
window.galet-window columnview > listview > row:selected,
window.galet-window listview > row:selected {{ background: alpha({v['accent']}, 0.22); color: {v['fg']}; }}
window.galet-window headerbar button:checked,
window.galet-window headerbar button:checked:hover {{ background: alpha({v['fg']}, 0.13); color: {v['fg']}; }}

.galet-window .navigation-sidebar > row,
.galet-window gridview > child,
.galet-window listview > row,
.galet-window button,
.galet-window popover > contents {{ border-radius: {radius}px; }}
.galet-window .galet-bottombar {{ border-top: 1px solid {v['line']}; }}
"""]
    if values.get("font"):
        css.append(f'.galet-window, .galet-window * {{ font-family: "{values["font"]}"; }}')

    if values.get("buttons") == "traffic":
        css.append("""
.galet-window windowcontrols > button { min-width: 14px; min-height: 14px; padding: 0; margin: 0 4px;
  background: none; box-shadow: none; }
.galet-window windowcontrols > button > image { min-width: 12px; min-height: 12px; padding: 0;
  border-radius: 50%; color: transparent; -gtk-icon-size: 8px;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.12); }
.galet-window windowcontrols > button.close > image { background-color: #ff5f57; }
.galet-window windowcontrols > button.minimize > image { background-color: #febc2e; }
.galet-window windowcontrols > button.maximize > image { background-color: #28c840; }
.galet-window windowcontrols:hover > button > image { color: rgba(0, 0, 0, 0.55); }
.galet-window:backdrop windowcontrols > button > image { background-color: alpha(currentColor, 0.2); }
""")
    elif values.get("buttons") == "windows":
        css.append("""
.galet-window windowcontrols > button { min-width: 44px; min-height: 30px; padding: 0; margin: 0;
  border-radius: 0; background: none; box-shadow: none; }
.galet-window windowcontrols > button > image { background: none; box-shadow: none; padding: 0; }
.galet-window windowcontrols > button:hover { background-color: alpha(currentColor, 0.08); }
.galet-window windowcontrols > button.close:hover { background-color: #c42b1c; color: #ffffff; }
""")

    if values.get("selection") == "mac":
        css.append(f"""
window.galet-window .navigation-sidebar > row:selected,
window.galet-window .navigation-sidebar > row:selected:hover,
window.galet-window .navigation-sidebar > row:selected:focus {{ background: alpha({values['fg']}, 0.10);
  color: {values['fg']}; }}
window.galet-window columnview > listview > row:selected,
window.galet-window listview.galet-column-list > row:selected {{ background: {values['accent']};
  color: #ffffff; }}
window.galet-window gridview > child:selected {{ background: alpha({values['fg']}, 0.10); }}
""")
    elif values.get("selection") == "windows":
        css.append(f"""
window.galet-window .navigation-sidebar > row:selected,
window.galet-window .navigation-sidebar > row:selected:hover,
window.galet-window .navigation-sidebar > row:selected:focus {{ background: alpha({values['fg']}, 0.07);
  color: {values['fg']}; box-shadow: inset 3px 0 {values['accent']}; }}
window.galet-window gridview > child:selected,
window.galet-window columnview > listview > row:selected,
window.galet-window listview > row:selected {{ background: alpha({values['accent']}, 0.18);
  box-shadow: inset 0 0 0 1px alpha({values['accent']}, 0.45); color: {values['fg']}; }}
""")
    return "\n".join(css)


def decoration_layout(settings):
    """GTK window-button layout for the theme, or None to follow the system."""
    values = resolve(settings, False)
    if values is None:
        return None
    return LAYOUTS.get(values.get("controls"))


class ThemeManager:
    def __init__(self, settings):
        self.settings = settings
        self.provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 10)
        self.style_manager = Adw.StyleManager.get_default()
        self.style_manager.connect("notify::dark", lambda *_a: self.apply())
        settings.connect("changed", self._on_setting)
        self.apply()

    def _on_setting(self, _settings, key):
        if key == "theme" or key == "color_scheme" or key.startswith("custom_"):
            self.apply()

    def apply(self):
        scheme = {"light": Adw.ColorScheme.FORCE_LIGHT, "dark": Adw.ColorScheme.FORCE_DARK}.get(
            self.settings.get("color_scheme", "auto"), Adw.ColorScheme.DEFAULT)
        if self.style_manager.get_color_scheme() != scheme:
            self.style_manager.set_color_scheme(scheme)
        forced = self.settings.get("color_scheme", "auto")
        dark = forced == "dark" if forced in ("light", "dark") else self.style_manager.get_dark()
        values = resolve(self.settings, dark)
        self.provider.load_from_string(build_css(values))


def draw_preview(cr, width, height, name, dark):
    """Tiny window mock-up used by the theme picker."""
    theme = THEMES.get(name, {})
    if "accent" in theme:
        colors = theme["dark" if dark else "light"]
        accent, sidebar, content = theme["accent"], colors["sidebar"], colors["content"]
        buttons = theme["buttons"]
    else:
        sidebar, content = ("#2e2e32", "#242428") if dark else ("#ebebed", "#fafafb")
        accent = "#3584e4" if name == "system" else "#8e44ad"
        buttons = "system"

    def rgb(color):
        rgba = Gdk.RGBA()
        rgba.parse(color)
        return rgba.red, rgba.green, rgba.blue

    radius = 8
    cr.new_sub_path()
    cr.arc(width - radius, radius, radius, -1.5708, 0)
    cr.arc(width - radius, height - radius, radius, 0, 1.5708)
    cr.arc(radius, height - radius, radius, 1.5708, 3.1416)
    cr.arc(radius, radius, radius, 3.1416, 4.7124)
    cr.close_path()
    cr.clip()
    cr.set_source_rgb(*rgb(content))
    cr.paint()
    cr.set_source_rgb(*rgb(sidebar))
    cr.rectangle(0, 0, width * 0.32, height)
    cr.fill()
    # sidebar rows
    for index in range(4):
        cr.set_source_rgb(*rgb(accent if index == 1 else ("#5a5a5e" if dark else "#c5c5c8")))
        cr.rectangle(width * 0.05, height * (0.30 + index * 0.14), width * 0.20, height * 0.06)
        cr.fill()
    # file icons
    for index in range(6):
        x = width * (0.40 + (index % 3) * 0.19)
        y = height * (0.30 + (index // 3) * 0.32)
        cr.set_source_rgb(*rgb(accent if index == 0 else ("#6b8fb8" if index % 2 else "#9bb7d6")))
        cr.rectangle(x, y, width * 0.12, height * 0.16)
        cr.fill()
    # window buttons
    if buttons == "traffic":
        for index, color in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            cr.set_source_rgb(*rgb(color))
            cr.arc(10 + index * 11, 10, 4, 0, 6.2832)
            cr.fill()
    elif buttons == "windows":
        cr.set_source_rgb(*rgb("#ffffff" if dark else "#333333"))
        cr.set_line_width(1.2)
        for index in range(3):
            x = width - 12 - index * 14
            cr.move_to(x - 4, 10)
            cr.line_to(x + 4, 10)
            cr.stroke()
    else:
        cr.set_source_rgb(*rgb("#888888"))
        cr.arc(width - 12, 10, 4, 0, 6.2832)
        cr.fill()
