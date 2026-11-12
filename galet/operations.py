"""Long-running file operations (copy, move...) with progress and cancel.

Work happens in a background thread; the ``Operation`` object is updated from
that thread and re-emits ``changed`` on the GTK main loop. The header bar shows
a progress pie with a popover listing operations, like Finder's toolbar.
"""

import math

from gi.repository import GLib, GObject, Gio, Gtk, Pango

from .i18n import _


class Operation(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, title):
        super().__init__()
        self.title = title
        self.detail = ""
        self.fraction = 0.0
        self.done = False
        self.cancellable = Gio.Cancellable()
        self._queued = False

    def update(self, detail=None, fraction=None):
        """Thread-safe: may be called from the worker thread."""
        if detail is not None:
            self.detail = detail
        if fraction is not None:
            self.fraction = max(0.0, min(1.0, fraction))
        if not self._queued:
            self._queued = True
            GLib.timeout_add(100, self._emit_changed)

    def _emit_changed(self):
        self._queued = False
        self.emit("changed")
        return GLib.SOURCE_REMOVE

    def finish(self):
        """Main thread only."""
        self.done = True
        self.fraction = 1.0
        self.emit("finished")


class ProgressPie(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(content_width=16, content_height=16)
        self.fraction = 0.0
        self.set_draw_func(self._draw)

    def set_fraction(self, fraction):
        self.fraction = fraction
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        color = self.get_color()
        cx, cy, radius = width / 2, height / 2, min(width, height) / 2 - 1
        cr.set_source_rgba(color.red, color.green, color.blue, 0.25)
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.fill()
        cr.set_source_rgba(color.red, color.green, color.blue, 1)
        cr.move_to(cx, cy)
        cr.arc(cx, cy, radius, -math.pi / 2, -math.pi / 2 + 2 * math.pi * self.fraction)
        cr.close_path()
        cr.fill()


class OperationsButton(Gtk.MenuButton):
    """Header-bar button that appears while files are being copied/moved."""

    def __init__(self):
        self.pie = ProgressPie()
        super().__init__(child=self.pie, visible=False, tooltip_text=_("File Operations"))
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin_top=6, margin_bottom=6,
                      margin_start=6, margin_end=6, width_request=320)
        box.append(self.list)
        self.set_popover(Gtk.Popover(child=box))
        self.operations = []

    def add(self, operation):
        self.operations.append(operation)
        row = Gtk.ListBoxRow(activatable=False)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin_top=8, margin_bottom=8,
                          margin_start=10, margin_end=10)
        top = Gtk.Box(spacing=6)
        title = Gtk.Label(label=operation.title, xalign=0, hexpand=True, css_classes=["heading"],
                          ellipsize=Pango.EllipsizeMode.END)
        cancel = Gtk.Button(icon_name="process-stop-symbolic", css_classes=["flat", "circular"],
                            tooltip_text=_("Cancel"))
        cancel.connect("clicked", lambda _b: operation.cancellable.cancel())
        top.append(title)
        top.append(cancel)
        detail = Gtk.Label(xalign=0, css_classes=["dim-label", "caption"], ellipsize=Pango.EllipsizeMode.MIDDLE)
        bar = Gtk.ProgressBar()
        content.append(top)
        content.append(detail)
        content.append(bar)
        row.set_child(content)
        self.list.append(row)

        def changed(op):
            detail.set_text(op.detail)
            bar.set_fraction(op.fraction)
            self._refresh()

        def finished(op):
            cancel.set_sensitive(False)
            changed(op)
            GLib.timeout_add(1500, lambda: self._remove(op, row))

        operation.connect("changed", changed)
        operation.connect("finished", finished)
        # Only show the button for operations lasting more than half a second.
        GLib.timeout_add(500, lambda: self._refresh() or False)

    def _remove(self, operation, row):
        if operation in self.operations:
            self.operations.remove(operation)
        self.list.remove(row)
        self._refresh()
        return GLib.SOURCE_REMOVE

    def _refresh(self):
        active = [op for op in self.operations if not op.done]
        if not self.operations:
            self.set_visible(False)
            self.popdown()
            return
        if active:
            self.set_visible(True)
            self.pie.set_fraction(sum(op.fraction for op in active) / len(active))
        else:
            self.pie.set_fraction(1.0)
