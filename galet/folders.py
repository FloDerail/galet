"""Coloured folders (right-click → folder colour), Finder-style.

The colour is stored as GIO metadata (``metadata::galet-folder-color``), so it
never modifies the folder itself. Icons are small SVGs generated on demand.
"""

from pathlib import Path

from gi.repository import Gio, GLib

from .i18n import N_

ATTRIBUTE = "metadata::galet-folder-color"
ICON_DIR = Path(GLib.get_user_cache_dir()) / "galet" / "folder-icons"

PALETTE = [
    (N_("Red"), "#ff453a"), (N_("Orange"), "#ff9f0a"), (N_("Yellow"), "#ffd60a"),
    (N_("Green"), "#30d158"), (N_("Teal"), "#40c8e0"), (N_("Blue"), "#0a84ff"),
    (N_("Purple"), "#bf5af2"), (N_("Pink"), "#ff375f"), (N_("Gray"), "#8e8e93"),
]

_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 64 64">
  <path d="M6 14a4 4 0 0 1 4-4h14l5 5h25a4 4 0 0 1 4 4v3H6z" fill="{dark}"/>
  <rect x="6" y="19" width="52" height="37" rx="4" fill="{color}"/>
  <rect x="6" y="19" width="52" height="3" rx="1.5" fill="#ffffff" fill-opacity="0.25"/>
</svg>
"""


def palette(settings):
    """The folder colours offered in menus (editable in Settings → Folders)."""
    custom = settings.get("folder_palette")
    if isinstance(custom, list) and custom:
        return [(str(c.get("name", "")), str(c.get("color"))) for c in custom if isinstance(c, dict) and c.get("color")]
    return list(PALETTE)


def effective_color(item, settings, tagstore):
    """Colour to draw a folder with: its own colour, else its tag's colour (optional),
    else the default folder colour (optional), else None (theme icon)."""
    if not item.is_dir:
        return None
    if item.folder_color:
        return item.folder_color
    if settings.get("folder_color_from_tags"):
        for tag in item.tags:
            color = tagstore.color_of(tag)
            if color:
                return color
    return settings.get("default_folder_color") or None


def _darker(color, factor=0.78):
    value = color.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return "#" + "".join(f"{int(c * factor):02x}" for c in (red, green, blue))


def icon_path(color):
    """Path to an SVG folder icon of ``color`` (created on first use)."""
    path = ICON_DIR / f"folder-{color.lstrip('#').lower()}.svg"
    if not path.exists():
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(_SVG.format(color=color, dark=_darker(color)), encoding="utf-8")
    return str(path)


def set_color(gfile, color):
    """Set (or clear, with ``None``) the colour of a folder. Raises GLib.Error."""
    gfile.set_attribute_string(ATTRIBUTE, color or "", Gio.FileQueryInfoFlags.NONE, None)
