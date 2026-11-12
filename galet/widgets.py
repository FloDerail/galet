"""Small reusable widgets: tag dots, tag picker, path bar."""

import math

import cairo
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import dnd
from .model import Location, display_name


class TagDots(Gtk.DrawingArea):
    """Overlapping coloured circles, like the tag dots in Finder."""

    def __init__(self, tagstore, size=10, max_dots=4):
        super().__init__(valign=Gtk.Align.CENTER, halign=Gtk.Align.START, visible=False)
        self.tagstore = tagstore
        self.size = size
        self.max_dots = max_dots
        self.marked = False
        self._colors = []
        self.set_content_height(size + 2)
        self.set_draw_func(self._draw)

    def set_tags(self, names):
        self.set_colors([self.tagstore.color_of(n) for n in names])
        self.set_tooltip_text(", ".join(names) if names else None)

    def set_colors(self, colors):
        self._colors = list(colors)[: self.max_dots]
        count = len(self._colors)
        step = self.size * 0.55
        self.set_content_width(int(math.ceil(self.size + 2 + step * max(count - 1, 0))))
        self.set_visible(count > 0)
        self.queue_draw()

    def _draw(self, _area, cr, _width, height):
        radius = self.size / 2
        step = self.size * 0.55
        cy = height / 2
        fg = self.get_color()
        # Draw right to left so the first tag sits on top, with a transparent
        # gap around each dot.
        for index in reversed(range(len(self._colors))):
            color = self._colors[index]
            cx = 1 + radius + index * step
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.arc(cx, cy, radius + 1.2, 0, 2 * math.pi)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)
            if color:
                rgba = Gdk.RGBA()
                rgba.parse(color)
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1)
                cr.arc(cx, cy, radius, 0, 2 * math.pi)
                cr.fill()
            else:
                cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.6)
                cr.set_line_width(1.3)
                cr.arc(cx, cy, radius - 0.7, 0, 2 * math.pi)
                cr.stroke()
        if self.marked and self._colors:
            cx = 1 + radius
            cr.set_source_rgba(1, 1, 1, 1)
            cr.set_line_width(max(1.6, self.size / 8))
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.set_line_join(cairo.LINE_JOIN_ROUND)
            cr.move_to(cx - radius * 0.45, cy + radius * 0.02)
            cr.line_to(cx - radius * 0.1, cy + radius * 0.35)
            cr.line_to(cx + radius * 0.45, cy - radius * 0.32)
            cr.stroke()


class TagPicker(Gtk.Box):
    """The row of coloured circles at the bottom of the context menu."""

    def __init__(self, tagstore, applied, on_toggle):
        super().__init__(spacing=0, halign=Gtk.Align.CENTER, margin_top=2, margin_bottom=2)
        self.add_css_class("tag-picker")
        for tag in [t for t in tagstore.tags if t["color"]][:9]:
            dots = TagDots(tagstore, size=16)
            dots.set_colors([tag["color"]])
            dots.marked = tag["name"] in applied
            button = Gtk.Button(child=dots, tooltip_text=tag["name"])
            button.add_css_class("flat")
            button.add_css_class("circular")
            button.connect("clicked", lambda _b, name=tag["name"]: on_toggle(name))
            self.append(button)


class PathBar(Gtk.ScrolledWindow):
    """Clickable breadcrumb shown at the bottom of the window."""

    def __init__(self, on_navigate, tagstore, on_drop=None):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                         vscrollbar_policy=Gtk.PolicyType.NEVER, hexpand=True)
        self.on_navigate = on_navigate
        self.on_drop = on_drop
        self.tagstore = tagstore
        self.box = Gtk.Box(spacing=0)
        self.set_child(self.box)

    def _clear(self):
        child = self.box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.box.remove(child)
            child = following

    def set_location(self, location):
        self._clear()
        if location.is_search:
            self.box.append(Gtk.Image(icon_name="system-search-symbolic", pixel_size=14, margin_start=8,
                                      margin_end=6))
            self.box.append(Gtk.Label(label=location.title, css_classes=["caption"]))
            return
        if location.is_tag:
            dots = TagDots(self.tagstore, 10)
            dots.set_colors([self.tagstore.color_of(location.tag)])
            dots.set_margin_start(8)
            dots.set_margin_end(6)
            self.box.append(dots)
            self.box.append(Gtk.Label(label=location.tag, css_classes=["caption"]))
            return

        home = Gio.File.new_for_path(GLib.get_home_dir())
        chain, gfile = [], location.gfile
        while gfile is not None:
            chain.append(gfile)
            if gfile.equal(home):
                break
            gfile = gfile.get_parent()
        chain.reverse()

        for index, gfile in enumerate(chain):
            if index:
                self.box.append(Gtk.Image(icon_name="go-next-symbolic", pixel_size=10,
                                          css_classes=["dim-label"]))
            if gfile.equal(home):
                icon = "user-home-symbolic"
            elif gfile.get_path() == "/":
                icon = "drive-harddisk-symbolic"
            else:
                icon = "folder-symbolic"
            content = Gtk.Box(spacing=4)
            content.append(Gtk.Image(icon_name=icon, pixel_size=14))
            content.append(Gtk.Label(label=display_name(gfile), ellipsize=Pango.EllipsizeMode.MIDDLE,
                                     max_width_chars=28, css_classes=["caption"]))
            button = Gtk.Button(child=content, css_classes=["flat", "pathbar-button"])
            button.connect("clicked", lambda _b, f=gfile: self.on_navigate(Location(f)))
            if self.on_drop is not None:
                dnd.add_drop_target(button, lambda f=gfile: f, self.on_drop)
                dnd.add_spring_load(button, lambda f=gfile: f, lambda f: self.on_navigate(Location(f)))
            self.box.append(button)

        GLib.idle_add(self._scroll_to_end)

    def _scroll_to_end(self):
        adjustment = self.get_hadjustment()
        adjustment.set_value(adjustment.get_upper())
        return GLib.SOURCE_REMOVE
