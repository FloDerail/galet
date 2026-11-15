"""Settings → Help: keyboard shortcuts and how to use Galet well.

The shortcuts are read from the real tables (application.ACCELS, pane.LOCAL_SHORTCUTS),
so this page can never disagree with what the keys actually do.
"""

from gi.repository import Adw, Gio, Gtk

from .i18n import _

GUIDE_URL = "https://floderail.github.io/galet/#guide"
ISSUES_URL = "https://github.com/FloDerail/galet/issues"


def _accels(action):
    from .application import ACCELS
    from .pane import LOCAL_SHORTCUTS

    found = list(ACCELS.get(action, []))
    found += [trigger for trigger, name in LOCAL_SHORTCUTS if name == action and trigger not in found]
    return found


def _shortcut_row(title, accels):
    row = Adw.ActionRow(title=title)
    box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
    for index, accel in enumerate(accels[:2]):
        if index:
            box.append(Gtk.Label(label=_("or"), css_classes=["dim-label", "caption"]))
        box.append(Gtk.ShortcutLabel(accelerator=accel))
    row.add_suffix(box)
    return row


def _shortcut_groups():
    sections = (
        (_("Windows and Tabs"), (
            (_("New window"), "app.new-window"), (_("New tab"), "win.new-tab"), (_("Close tab"), "win.close-tab"),
            (_("Settings"), "app.preferences"), (_("Help and shortcuts"), "app.help"), (_("Quit"), "app.quit"))),
        (_("Navigation"), (
            (_("Back"), "win.back"), (_("Forward"), "win.forward"), (_("Enclosing folder"), "win.up"),
            (_("Open"), "win.open"), (_("Open in a new tab"), "win.open-new-tab"),
            (_("Go to a location"), "win.go-to"), (_("Home folder"), "win.go-home"),
            (_("Desktop"), "win.go-desktop"), (_("Documents"), "win.go-documents"),
            (_("Downloads"), "win.go-downloads"), (_("Recent files"), "win.go-recent"),
            (_("Network"), "win.go-network"))),
        (_("View"), (
            (_("Icons"), "win.view-mode::grid"), (_("List"), "win.view-mode::list"),
            (_("Columns"), "win.view-mode::columns"), (_("Gallery"), "win.view-mode::gallery"),
            (_("Show hidden files"), "win.show-hidden"), (_("Preview pane"), "win.show-preview"),
            (_("Get info"), "win.get-info"), (_("Reload"), "win.reload"))),
        (_("Files"), (
            (_("Select all"), "win.select-all"), (_("Copy"), "win.copy"), (_("Cut"), "win.cut"),
            (_("Paste"), "win.paste"), (_("Duplicate"), "win.duplicate"), (_("Rename"), "win.rename"),
            (_("Move to the trash"), "win.trash"), (_("Delete permanently"), "win.delete-permanently"),
            (_("Undo"), "win.undo"), (_("New folder"), "win.new-folder"),
            (_("New folder with the selection"), "win.new-folder-with-selection"),
            (_("Quick Look"), "win.quicklook"), (_("Copy the path"), "win.copy-path"),
            (_("Tags"), "win.edit-tags"), (_("Context menu"), "win.context-menu"))),
        (_("Search"), ((_("Search"), "win.search"),)),
        (_("Servers, Terminal and Transfers"), (
            (_("Server manager"), "win.connect-server"), (_("Built-in terminal"), "win.toggle-terminal"),
            (_("Dual pane"), "win.dual-pane"))),
    )
    groups = []
    for title, rows in sections:
        group = Adw.PreferencesGroup(title=title)
        for label, action in rows:
            accels = _accels(action)
            if accels:
                group.add(_shortcut_row(label, accels))
        groups.append(group)
    # keys handled by widgets themselves
    groups[4].add(_shortcut_row(_("Close the search window"), ["Escape"]))
    groups[5].add(_shortcut_row(_("Copy in the terminal"), ["<Control><Shift>c"]))
    groups[5].add(_shortcut_row(_("Paste in the terminal"), ["<Control><Shift>v"]))
    return groups


GUIDE = (
    (_("Getting around"), "folder-symbolic", (
        (_("Four views"), _("Icons, List, Columns (with preview) and Gallery: Ctrl+1 to Ctrl+4. Each folder "
                             "remembers its own view.")),
        (_("Tabs"), _("Ctrl+T opens a tab; drop files on a tab to copy them there; drag a tab out to make a new "
                      "window.")),
        (_("Type to select"), _("In a folder, just type the beginning of a name to jump to it.")),
        (_("Quick Look"), _("Space shows a large preview of the selected file, like on a Mac.")))),
    (_("Tags and colours"), "galet-tag-symbolic", (
        (_("Tag a file or folder"), _("Right-click → a colour dot. Tags are stored in the files themselves and "
                                      "follow them when they are moved.")),
        (_("Find everything with a tag"), _("Click the tag in the sidebar.")),
        (_("Folder colours"), _("Right-click a folder → Folder Colour. A folder can also take the colour of its "
                                "tag (Settings → Folders).")))),
    (_("Search"), "system-search-symbolic", (
        (_("Big search bar"), _("Ctrl+F: search names and even the content of documents and code. Choose the "
                                "classic bar or the big one in Settings → General.")),
        (_("Simple or AI mode"), _("The AI mode understands sentences (“photos of the beach”, “a piece of code "
                                   "that reads JSON”). It is off by default (Settings → AI).")),
        (_("Smart folders"), _("Save a search to find it again in the sidebar.")))),
    (_("Servers"), "network-server-symbolic", (
        (_("Add a server"), _("Ctrl+K → New Server: protocol (SFTP, SMB, WebDAV, FTP…), host, port, folder and "
                              "user name. The password goes to the GNOME keyring.")),
        (_("Connect"), _("Click the server in the sidebar. If a password is needed, Galet asks for it; if the "
                         "connection fails, a message explains why.")),
        (_("SSH keys"), _("For SFTP, your keys in ~/.ssh are used automatically: no password needed.")))),
    (_("Transfers"), "view-dual-symbolic", (
        (_("Dual pane"), _("F3 (or “Transfer” on a server card): your computer on one side, the server on the "
                           "other. Drag and drop, or right-click → Copy to the Other Side.")),
        (_("Merge"), _("Copying a folder that already exists? Choose Merge: only new and modified files are "
                       "copied, nothing is deleted.")),
        (_("Synchronise"), _("The ⟳ button of the dual pane compares both folders and shows a preview before "
                             "sending only what changed. ⇄ reverses the direction.")))),
    (_("Git and GitHub for beginners"), "system-users-symbolic", (
        (_("Install"), _("In a terminal (F4): sudo apt install git gh")),
        (_("Sign in to GitHub"), _("gh auth login → GitHub.com → HTTPS → “Login with a web browser”: copy the "
                                   "code shown, the browser opens, paste it and accept. Done once.")),
        (_("Tell Git who you are"), _("git config --global user.name \"Your Name\" then git config --global "
                                      "user.email \"you@example.com\" (once).")),
        (_("A new project"), _("In the project folder: git init, git add ., git commit -m \"First version\", "
                               "then gh repo create --source=. --private --push creates it on GitHub.")),
        (_("A project already on GitHub"), _("gh repo clone your-name/project copies it to your computer.")),
        (_("Every day"), _("git add . then git commit -m \"What I changed\" then git push. Galet does not need "
                           "your GitHub account: it reads the project on your computer.")))),
    (_("Deploy with Git"), "send-to-symbolic", (
        (_("1. Push"), _("Work as usual, then git add, git commit and git push.")),
        (_("2. Open the project and the server"), _("Your Git project on one side of the dual pane (F3), the "
                                                    "server folder (e.g. www) on the other.")),
        (_("3. Deploy"), _("A banner shows the commits pushed since the last deployment. “Deploy…” sends only "
                           "the files those commits changed.")),
        (_("What is never sent"), _("Uncommitted changes, commits not pushed yet, and files ignored by Git "
                                    "(.env, node_modules).")),
        (_("Pushed from another computer?"), _("Run git pull (or git fetch) in the project first.")),
        (_("The server already has the site?"), _("On the first deployment, click “The Server Is Already Up to "
                                                  "Date”: nothing is sent, and next time only your new commits "
                                                  "are.")))),
    (_("Built-in terminal"), "utilities-terminal-symbolic", (
        (_("Open it"), _("F4 or Ctrl+² (the key under Esc): a terminal under the files, in the current folder.")),
        (_("On a server"), _("On an SFTP server, it opens an SSH session in the same folder.")),
        (_("Keyboard"), _("While you type in it, Ctrl+C, Ctrl+R, Ctrl+L… go to the terminal. Copy and paste "
                          "with Ctrl+Shift+C and Ctrl+Shift+V.")))),
    (_("Security and backups"), "security-high-symbolic", (
        (_("Encrypted server list"), _("Your servers are encrypted (AES-256). A master password can lock "
                                       "them like a vault (Settings → Servers → Security).")),
        (_("Backups"), _("Settings → Advanced → Backup: settings, tags, colours, favourites and servers in one "
                         "file, encrypted with a password. API keys and passwords are never included.")))),
)


def help_page(window_getter):
    page = Adw.PreferencesPage(title=_("Help"), icon_name="help-browser-symbolic")

    guide = Adw.PreferencesGroup(title=_("Using Galet Well"),
                                 description=_("The essentials, topic by topic. The full guide with pictures is "
                                               "on the website."))
    for title, icon, items in GUIDE:
        expander = Adw.ExpanderRow(title=title)
        expander.add_prefix(Gtk.Image(icon_name=icon))
        for item_title, text in items:
            row = Adw.ActionRow(title=item_title, subtitle=text, subtitle_lines=0)
            expander.add_row(row)
        guide.add(expander)
    page.add(guide)

    links = Adw.PreferencesGroup(title=_("More Help"))
    for title, subtitle, url, icon in (
            (_("Full guide on the website"), GUIDE_URL, GUIDE_URL, "web-browser-symbolic"),
            (_("Report a problem or suggest an idea"),
             _("Attach the log file: ~/.cache/galet/galet.log (Flatpak: "
               "~/.var/app/io.github.FloDerail.Galet/cache/galet/galet.log)"), ISSUES_URL, "dialog-question-symbolic")):
        row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True, subtitle_lines=0)
        row.add_prefix(Gtk.Image(icon_name=icon))
        row.add_suffix(Gtk.Image(icon_name="adw-external-link-symbolic"))
        row.connect("activated", lambda _r, u=url: Gtk.UriLauncher.new(u).launch(window_getter(), None, None, None))
        links.add(row)
    page.add(links)

    intro = Adw.PreferencesGroup(title=_("Keyboard Shortcuts"),
                                 description=_("Ctrl+letter shortcuts are left to the terminal while you type in "
                                               "it."))
    page.add(intro)
    for group in _shortcut_groups():
        page.add(group)
    return page
