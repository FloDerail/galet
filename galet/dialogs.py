"""Tag editing dialogs."""

from gi.repository import Adw, Gtk

from .i18n import _, ngettext
from .tags import PALETTE
from .widgets import TagDots


def edit_tags(window, items):
    """Finder's "Tags…" dialog: tick tags for the selection, create new ones."""
    tagstore = window.tagstore
    paths = [i.path for i in items if i.path]
    if not paths:
        return
    current = {p: set(tagstore.read(p)) for p in paths}

    body = items[0].name if len(items) == 1 else \
        ngettext("{n} item", "{n} items", len(items)).format(n=len(items))
    dialog = Adw.AlertDialog(heading=_("Tags"), body=body)

    listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
    checks = {}

    def add_row(name, color):
        row = Adw.ActionRow(title=name)
        check = Gtk.CheckButton(valign=Gtk.Align.CENTER)
        count = sum(1 for tags in current.values() if name in tags)
        if count == len(paths):
            check.set_active(True)
        elif count:
            check.set_inconsistent(True)
        check.connect("toggled", lambda c: c.set_inconsistent(False))
        row.add_prefix(check)
        row.set_activatable_widget(check)
        dots = TagDots(tagstore, 12)
        dots.set_colors([color])
        row.add_suffix(dots)
        listbox.append(row)
        checks[name] = check

    known = {t["name"] for t in tagstore.tags}
    for tag in tagstore.tags:
        add_row(tag["name"], tag["color"])
    for name in sorted(set().union(*current.values()) - known):
        add_row(name, None)

    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                  max_content_height=300)
    scroller.set_child(listbox)

    colors = Gtk.DropDown.new_from_strings([_("No Color")] + [_(name) for name, _c in PALETTE])
    colors.set_valign(Gtk.Align.CENTER)
    new_row = Adw.EntryRow(title=_("New Tag"), show_apply_button=True)
    new_row.add_suffix(colors)

    def create(_row):
        name = new_row.get_text().strip()
        if not name:
            return
        index = colors.get_selected()
        color = PALETTE[index - 1][1] if index > 0 else None
        name = tagstore.add_tag(name, color)
        if name not in checks:
            add_row(name, color)
        checks[name].set_active(True)
        new_row.set_text("")

    new_row.connect("apply", create)
    new_row.connect("entry-activated", create)
    new_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"])
    new_list.append(new_row)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.append(scroller)
    box.append(new_list)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("apply", _("Apply"))
    dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("apply")
    dialog.set_close_response("cancel")

    def on_response(_dialog, response):
        if response != "apply":
            return
        try:
            for path in paths:
                tags = list(tagstore.read(path))
                for name, check in checks.items():
                    if check.get_inconsistent():
                        continue
                    if check.get_active() and name not in tags:
                        tags.append(name)
                    elif not check.get_active() and name in tags:
                        tags.remove(name)
                tagstore.write(path, tags)
        except OSError as err:
            window.toast(_("Could not change tags: {error}").format(error=err.strerror or err))

    dialog.connect("response", on_response)
    dialog.present(window)


def delete_tag(window, name):
    tagstore = window.tagstore
    dialog = Adw.AlertDialog(heading=_("Delete Tag “{name}”?").format(name=name),
                             body=_("The tag will be removed from all files."))
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("delete", _("Delete"))
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, r: tagstore.remove_tag(name) if r == "delete" else None)
    dialog.present(window)
