"""The "Synchronise" window of the dual pane: preview, then send only what changed."""

import threading

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import sync
from .i18n import _, ngettext

MAX_ROWS = 1500


def _kind_label(entry):
    if entry.kind == sync.NEW:
        return _("New folder") if entry.is_dir else _("New")
    return {sync.MODIFIED: _("Modified"), sync.NEWER_THERE: _("More recent at destination"),
            sync.EXTRA: _("To delete")}[entry.kind]


def _kind_icon(entry):
    return {sync.NEW: "list-add-symbolic", sync.MODIFIED: "document-edit-symbolic",
            sync.NEWER_THERE: "dialog-warning-symbolic", sync.EXTRA: "user-trash-symbolic"}[entry.kind]


class SyncDialog(Adw.Dialog):
    def __init__(self, window, source, destination, source_title, destination_title):
        super().__init__(title=_("Synchronise"), content_width=660, content_height=640)
        self.window = window
        self.ends = [(source, source_title), (destination, destination_title)]
        self.plan = None
        self.cancellable = None
        self.generation = 0

        self.send_button = Gtk.Button(label=_("Send"), css_classes=["suggested-action"], sensitive=False)
        self.send_button.connect("clicked", lambda *_a: self._send())
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_a: self.close())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.send_button)

        # direction: source → destination, with a swap button
        self.from_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=["heading"], hexpand=True,
                                    xalign=1)
        self.to_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=["heading"], hexpand=True,
                                  xalign=0)
        swap = Gtk.Button(icon_name="object-flip-horizontal-symbolic", tooltip_text=_("Reverse the direction"),
                          css_classes=["circular"], valign=Gtk.Align.CENTER)
        swap.connect("clicked", lambda *_a: self._swap())
        direction = Gtk.Box(spacing=10, margin_top=6, margin_bottom=6)
        direction.append(self.from_label)
        direction.append(Gtk.Image(icon_name="go-next-symbolic"))
        direction.append(self.to_label)
        direction.append(swap)

        self.exclude_row = Adw.SwitchRow(title=_("Ignore .git, node_modules and temporary files"), active=True)
        self.mirror_row = Adw.SwitchRow(
            title=_("Also delete at the destination what no longer exists at the source"),
            subtitle=_("Off by default. Deleted items go to the trash when possible."))
        for row in (self.exclude_row, self.mirror_row):
            row.connect("notify::active", lambda *_a: self._scan())
        options = Adw.PreferencesGroup()
        options.add(self.exclude_row)
        options.add(self.mirror_row)

        self.spinner = Gtk.Spinner()
        self.status = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        status_row = Gtk.Box(spacing=8)
        status_row.append(self.spinner)
        status_row.append(self.status)
        self.toggle_all = Gtk.Button(label=_("Select All"), css_classes=["flat"], visible=False)
        self.toggle_all.connect("clicked", lambda *_a: self._toggle_all())
        status_row.append(self.toggle_all)

        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
                                valign=Gtk.Align.START)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=18,
                      margin_start=18, margin_end=18)
        for widget in (direction, options, status_row, scroller):
            box.append(widget)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(box)
        self.set_child(toolbar)
        self.connect("closed", lambda *_a: self._cancel_scan())
        self._update_direction()
        self._scan()

    # ------------------------------------------------------------- scanning

    def _update_direction(self):
        (_src, src_title), (_dst, dst_title) = self.ends
        self.from_label.set_text(src_title)
        self.to_label.set_text(dst_title)

    def _swap(self):
        self.ends.reverse()
        self._update_direction()
        self._scan()

    def _cancel_scan(self):
        if self.cancellable is not None:
            self.cancellable.cancel()

    def _scan(self):
        self._cancel_scan()
        self.generation += 1
        generation = self.generation
        self.cancellable = cancellable = Gio.Cancellable()
        (source, _t), (destination, _t2) = self.ends
        excludes = sync.DEFAULT_EXCLUDES if self.exclude_row.get_active() else ()
        mirror = self.mirror_row.get_active()
        self.plan = None
        self.send_button.set_sensitive(False)
        self.toggle_all.set_visible(False)
        self.list.remove_all()
        self.spinner.set_visible(True)
        self.spinner.start()
        self.status.set_text(_("Comparing the two folders…"))
        last = {"time": 0}

        def progress(path):
            now = GLib.get_monotonic_time()
            if now - last["time"] > 150000:
                last["time"] = now
                GLib.idle_add(lambda: generation == self.generation and
                              self.status.set_text(_("Comparing… {path}").format(path=path)) and False)

        def work():
            plan = sync.scan(source, destination, excludes, mirror, cancellable, progress)
            GLib.idle_add(lambda: self._show_plan(plan, generation) and False)

        threading.Thread(target=work, daemon=True).start()

    def _show_plan(self, plan, generation):
        if generation != self.generation or self.cancellable.is_cancelled():
            return
        self.plan = plan
        self.spinner.stop()
        self.spinner.set_visible(False)
        parts = []
        for kind, text in ((sync.MODIFIED, ngettext("{n} modified file", "{n} modified files", plan.count(sync.MODIFIED))),
                           (sync.NEW, ngettext("{n} new item", "{n} new items", plan.count(sync.NEW))),
                           (sync.NEWER_THERE, ngettext("{n} item more recent at destination",
                                                       "{n} items more recent at destination",
                                                       plan.count(sync.NEWER_THERE))),
                           (sync.EXTRA, ngettext("{n} item to delete", "{n} items to delete", plan.count(sync.EXTRA)))):
            if plan.count(kind):
                parts.append(text.format(n=plan.count(kind)))
        parts.append(ngettext("{n} identical file (skipped)", "{n} identical files (skipped)", plan.same).format(n=plan.same))
        summary = " · ".join(parts)
        if not plan.entries:
            summary = _("Everything is already up to date.") + " " + summary
        if plan.errors:
            summary += "\n" + _("Some folders could not be read: {error}").format(error=plan.errors[0])
        self.status.set_text(summary)
        for entry in plan.entries[:MAX_ROWS]:
            self.list.append(self._row(entry))
        if len(plan.entries) > MAX_ROWS:
            more = Adw.ActionRow(title=_("… and {n} more").format(n=len(plan.entries) - MAX_ROWS))
            self.list.append(more)
        self.toggle_all.set_visible(bool(plan.entries))
        self._update_send()

    def _row(self, entry):
        row = Adw.ActionRow(title=GLib.markup_escape_text(entry.path), subtitle=_kind_label(entry),
                            title_lines=1, activatable=True)
        row.set_title_selectable(False)
        check = Gtk.CheckButton(active=entry.selected, valign=Gtk.Align.CENTER)
        check.connect("toggled", lambda button: (setattr(entry, "selected", button.get_active()),
                                                 self._update_send()))
        row.add_prefix(check)
        row.set_activatable_widget(check)
        icon = Gtk.Image(icon_name=_kind_icon(entry))
        if entry.kind == sync.EXTRA:
            icon.add_css_class("error")
        elif entry.kind == sync.NEWER_THERE:
            icon.add_css_class("warning")
        row.add_prefix(icon)
        if not entry.is_dir and entry.kind != sync.EXTRA:
            row.add_suffix(Gtk.Label(label=sync.human_size(entry.size), css_classes=["dim-label", "caption"]))
        row.entry = entry
        row.check = check
        return row

    def _toggle_all(self):
        rows = []
        child = self.list.get_first_child()
        while child is not None:
            if hasattr(child, "check"):
                rows.append(child)
            child = child.get_next_sibling()
        select = not all(r.check.get_active() for r in rows)
        for row in rows:
            row.check.set_active(select)
        for entry in self.plan.entries[MAX_ROWS:]:
            entry.selected = select

    def _update_send(self):
        if self.plan is None:
            return
        chosen = self.plan.selected()
        files = sum(1 for e in chosen if not e.is_dir and e.kind != sync.EXTRA)
        deletions = sum(1 for e in chosen if e.kind == sync.EXTRA)
        size = sum(e.size for e in chosen if not e.is_dir and e.kind != sync.EXTRA)
        label = ngettext("Send {n} file", "Send {n} files", files).format(n=files)
        if size:
            label += f" ({sync.human_size(size)})"
        if deletions:
            label += " · " + ngettext("delete {n} item", "delete {n} items", deletions).format(n=deletions)
        self.send_button.set_label(label if chosen else _("Send"))
        self.send_button.set_sensitive(bool(chosen))
        all_on = bool(self.plan.entries) and len(chosen) == len(self.plan.entries)
        self.toggle_all.set_label(_("Select None") if all_on else _("Select All"))

    # --------------------------------------------------------------- send

    def _send(self):
        from . import fileops

        plan = self.plan
        entries = plan.selected()
        if not entries:
            return
        window = self.window
        deletions = [e for e in entries if e.kind == sync.EXTRA]
        self.close()

        def work(operation, errors):
            def progress(index, total, path, fraction):
                operation.update(detail=_("{current} of {total} — {name}").format(current=index + 1, total=total,
                                                                                 name=path),
                                 fraction=(index + fraction) / max(1, total))

            done, failed = sync.apply(plan, entries, operation.cancellable, progress)
            errors.extend(failed)
            return done

        def finished(done, errors):
            for pane in window.panes:
                location = pane.location
                if not location.is_virtual and (location.gfile.equal(plan.destination)
                                                or location.gfile.has_prefix(plan.destination)
                                                or plan.destination.has_prefix(location.gfile)):
                    pane.reload()  # servers do not always report changes
            if errors:
                window.toast(_("Some items could not be synchronised: {error}").format(error=errors[0]))
            else:
                window.toast(ngettext("Synchronised: {n} item", "Synchronised: {n} items", done or 0)
                             .format(n=done or 0))

        title = _("Synchronising to “{name}”").format(name=self.ends[1][1])
        if deletions:
            confirm = Adw.AlertDialog(
                heading=_("Delete {n} items at the destination?").format(n=len(deletions)),
                body=_("They no longer exist at the source. They go to the trash when the destination supports it; "
                       "on most servers they are deleted for good."))
            confirm.add_response("cancel", _("Cancel"))
            confirm.add_response("go", _("Synchronise"))
            confirm.set_response_appearance("go", Adw.ResponseAppearance.DESTRUCTIVE)
            confirm.set_close_response("cancel")
            confirm.connect("response", lambda _d, r: r == "go" and fileops._run(window, title, work, finished))
            confirm.present(window)
        else:
            fileops._run(window, title, work, finished)


def open_for(window, source_pane, destination_pane):
    from . import servers

    if source_pane is None or destination_pane is None:
        return
    for pane in (source_pane, destination_pane):
        if pane.location.is_virtual:
            window.toast(_("Synchronising works between two real folders."))
            return
    source, destination = source_pane.location.gfile, destination_pane.location.gfile
    if source.equal(destination) or destination.has_prefix(source) or source.has_prefix(destination):
        window.toast(_("Choose two different folders, not one inside the other."))
        return

    def show():
        SyncDialog(window, source, destination, source_pane.location.title,
                   destination_pane.location.title).present(window)

    servers.ensure_mounted(window, destination, lambda: servers.ensure_mounted(window, source, show))
