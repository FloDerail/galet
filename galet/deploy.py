"""Deploy with Git: send to a server only the files changed by the commits you pushed.

A project folder (inside a Git repository) is paired with a server folder. Galet
remembers the last deployed commit of each pair (encrypted in the vault, like the
servers). The files to send are ``git diff --name-status <deployed>..<pushed>``,
where "pushed" is the upstream branch (``origin/main``) — what is on GitHub — or the
current branch when there is no upstream. The content sent is the one of that
commit (``git show``), not your uncommitted changes. Files deleted in Git are
offered for deletion on the server, unchecked by default.

The first deployment of a pair has no reference commit: Galet compares the files
tracked by Git with the server (size and date), then remembers the commit.
"""

import os
import subprocess
import tempfile
import threading
import time

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import sync
from .i18n import _, ngettext

VAULT_KEY = "deploys"
GVFS_ROOT = os.path.join(GLib.get_user_runtime_dir(), "gvfs") + os.sep
DELETED = "deleted"


class GitError(Exception):
    pass


# ---------------------------------------------------------------------- git

def _git_command():
    from .sandbox import find_program
    return find_program("git")


def git(directory, *args, binary=False):
    command = _git_command()
    if command is None:
        raise GitError(_("Git is not installed."))
    try:
        result = subprocess.run([*command, "-C", directory, *args], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as err:
        raise GitError(str(err)) from err
    if result.returncode != 0:
        raise GitError(result.stderr.decode("utf-8", "replace").strip() or "git failed")
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


def repo_root(path):
    """Top folder of the Git repository containing ``path``, or None."""
    if not path or not os.path.isdir(path):
        return None
    try:
        return git(path, "rev-parse", "--show-toplevel").strip() or None
    except GitError:
        return None


class Project:
    """A local folder inside a Git repository."""

    def __init__(self, folder):
        self.folder = os.path.realpath(folder)
        self.root = repo_root(self.folder)
        if self.root is None:
            raise GitError(_("This folder is not in a Git repository."))
        self.root = os.path.realpath(self.root)
        prefix = os.path.relpath(self.folder, self.root)
        self.prefix = "" if prefix == "." else prefix.replace(os.sep, "/") + "/"
        self.branch = git(self.root, "rev-parse", "--abbrev-ref", "HEAD").strip()
        try:
            self.upstream = git(self.root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}").strip()
        except GitError:
            self.upstream = None
        self.target_ref = self.upstream or "HEAD"
        self.target = git(self.root, "rev-parse", self.target_ref).strip()

    def has_commit(self, sha):
        try:
            git(self.root, "cat-file", "-e", f"{sha}^{{commit}}")
            return True
        except GitError:
            return False

    def commits(self, base):
        out = git(self.root, "log", "--format=%h%x09%s", f"{base}..{self.target}", "--", self.prefix or ".")
        return [line.split("\t", 1) for line in out.splitlines() if "\t" in line]

    def changes(self, base):
        """[(status, path relative to the project folder)] between ``base`` and the target."""
        out = git(self.root, "diff", "--name-status", "--no-renames", "-z", base, self.target, "--",
                  self.prefix or ".")
        parts = out.split("\0")
        result = []
        for status, path in zip(parts[0::2], parts[1::2]):
            if path and path.startswith(self.prefix):
                result.append((status[:1], path[len(self.prefix):]))
        return result

    def tracked(self):
        out = git(self.root, "ls-tree", "-r", "-z", "--name-only", self.target, "--", self.prefix or ".")
        return {p[len(self.prefix):] for p in out.split("\0") if p and p.startswith(self.prefix)}

    def content(self, path):
        return git(self.root, "show", f"{self.target}:{self.prefix}{path}", binary=True)


# -------------------------------------------------------------- remembered

def _pairs(settings):
    from . import vault
    return vault.get(settings).get_list(VAULT_KEY)


def last_deploy(settings, folder, remote_uri):
    folder = os.path.realpath(folder)
    for pair in _pairs(settings):
        if pair.get("local") == folder and pair.get("remote") == remote_uri:
            return pair
    return None


def remember(settings, folder, remote_uri, project):
    from . import vault

    folder = os.path.realpath(folder)
    pairs = [p for p in _pairs(settings) if not (p.get("local") == folder and p.get("remote") == remote_uri)]
    pairs.append({"local": folder, "remote": remote_uri, "commit": project.target, "branch": project.target_ref,
                  "date": int(time.time())})
    vault.get(settings).set_list(VAULT_KEY, pairs)


def pending(settings, folder, remote_uri):
    """(project, n_commits) waiting to be deployed for this pair, or None."""
    pair = last_deploy(settings, folder, remote_uri)
    if pair is None:
        return None
    try:
        project = Project(folder)
        if not project.has_commit(pair["commit"]) or pair["commit"] == project.target:
            return None
        return project, len(project.commits(pair["commit"]))
    except GitError:
        return None


# ------------------------------------------------------------------ plan

def prepare(settings, folder, remote):
    """Fast part (Git only): (project, base commit or None, commits)."""
    project = Project(folder)
    pair = last_deploy(settings, folder, remote.get_uri())
    base = pair["commit"] if pair and project.has_commit(pair["commit"]) else None
    return project, base, project.commits(base) if base else []


def build_plan(settings, folder, remote, cancellable=None, progress=None, prepared=None):
    """Return (project, plan, commits, base) — plan entries use the sync kinds plus DELETED."""
    project, base, commits = prepared or prepare(settings, folder, remote)
    plan = sync.Plan(Gio.File.new_for_path(project.folder), remote)
    if base is not None:
        for status, path in project.changes(base):
            if status == "D":
                entry = sync.Entry(path, DELETED)
                entry.selected = False
            else:
                entry = sync.Entry(path, sync.NEW if status == "A" else sync.MODIFIED)
            plan.entries.append(entry)
    else:  # first deployment: tracked files compared with the server (size and date)
        tracked = project.tracked()
        # only the folders that contain tracked files are visited on the server
        scanned = sync.scan(Gio.File.new_for_path(project.folder), remote, (".git",), False, cancellable,
                            progress, only=tracked)
        plan.errors = scanned.errors
        for entry in scanned.entries:
            if entry.is_dir or entry.path not in tracked:
                continue
            plan.entries.append(entry)
        plan.same = scanned.same
    return project, plan, commits, base


def apply(project, plan, entries, cancellable=None, progress=None):
    """Send the committed content of ``entries`` (and delete DELETED ones). Returns (done, errors)."""
    done, errors = 0, []
    total = len(entries)
    with tempfile.TemporaryDirectory(prefix="galet-deploy-") as tmp:
        for index, entry in enumerate(entries):
            if cancellable is not None and cancellable.is_cancelled():
                break
            if progress:
                progress(index, total, entry.path)
            destination = plan.destination.resolve_relative_path(entry.path)
            try:
                if entry.kind == DELETED:
                    try:
                        destination.delete(cancellable)
                    except GLib.Error as err:
                        if not err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.NOT_FOUND):
                            raise
                else:
                    local = os.path.join(tmp, "blob")
                    with open(local, "wb") as handle:
                        handle.write(project.content(entry.path))
                    parent = destination.get_parent()
                    if parent is not None and not parent.query_exists(cancellable):
                        parent.make_directory_with_parents(cancellable)
                    Gio.File.new_for_path(local).copy(destination, Gio.FileCopyFlags.OVERWRITE, cancellable,
                                                      None, None)
                done += 1
            except (GLib.Error, GitError, OSError) as err:
                if isinstance(err, GLib.Error) and err.matches(Gio.io_error_quark(), Gio.IOErrorEnum.CANCELLED):
                    break
                errors.append(f"{entry.path}: {getattr(err, 'message', None) or err}")
    return done, errors


# ---------------------------------------------------------------- window

def _kind_label(entry):
    return {sync.NEW: _("Added"), sync.MODIFIED: _("Modified"), DELETED: _("Deleted in Git"),
            sync.NEWER_THERE: _("More recent at destination")}.get(entry.kind, entry.kind)


def _kind_icon(entry):
    return {sync.NEW: "list-add-symbolic", sync.MODIFIED: "document-edit-symbolic",
            DELETED: "user-trash-symbolic", sync.NEWER_THERE: "dialog-warning-symbolic"}.get(entry.kind,
                                                                                            "text-x-generic-symbolic")


class DeployDialog(Adw.Dialog):
    def __init__(self, window, folder, remote, remote_title):
        super().__init__(title=_("Deploy With Git"), content_width=660, content_height=640)
        self.window = window
        self.folder = folder
        self.remote = remote
        self.remote_title = remote_title
        self.project = self.plan = None
        self.rows = []

        self.send_button = Gtk.Button(label=_("Send"), css_classes=["suggested-action"], sensitive=False)
        self.send_button.connect("clicked", lambda *_a: self._send())
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda *_a: self.close())
        header = Adw.HeaderBar(show_start_title_buttons=False, show_end_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.send_button)

        self.title_label = Gtk.Label(css_classes=["heading"], wrap=True, xalign=0)
        self.info = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        self.spinner = Gtk.Spinner(spinning=True)
        top = Gtk.Box(spacing=8)
        top.append(self.spinner)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        text.append(self.title_label)
        text.append(self.info)
        top.append(text)

        self.uptodate_button = Gtk.Button(label=_("The Server Is Already Up to Date"), visible=False,
                                          halign=Gtk.Align.START, css_classes=["pill"])
        self.uptodate_button.set_tooltip_text(_("Remember the current commit as deployed without sending anything. "
                                                "Next time, only the files of your new commits will be sent."))
        self.uptodate_button.connect("clicked", lambda *_a: self._mark_up_to_date())
        self.cancellable = Gio.Cancellable()
        self.connect("closed", lambda *_a: self.cancellable.cancel())
        self.commits_row = Adw.ExpanderRow(title=_("Commits"), visible=False)
        commits_group = Adw.PreferencesGroup()
        commits_group.add(self.commits_row)

        self.list = Gtk.ListBox(css_classes=["boxed-list"], selection_mode=Gtk.SelectionMode.NONE,
                                valign=Gtk.Align.START)
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER, child=self.list)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=18,
                      margin_start=18, margin_end=18)
        for widget in (top, self.uptodate_button, commits_group, scroller):
            box.append(widget)
        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.set_content(box)
        self.set_child(toolbar)

        self.title_label.set_text(_("{project} → {server}").format(project=os.path.basename(folder.rstrip("/")),
                                                                   server=remote_title))
        self.info.set_text(_("Looking for the commits to deploy…"))
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self):
        try:
            prepared = prepare(self.window.settings, self.folder, self.remote)
            GLib.idle_add(lambda: self._prepared(*prepared) and False)
            last = {"time": 0}

            def progress(path, folders):
                now = GLib.get_monotonic_time()
                if now - last["time"] > 150000:
                    last["time"] = now
                    text = ngettext("Comparing with the server… {n} folder", "Comparing with the server… {n} folders",
                                    folders).format(n=folders) + "\n" + path
                    GLib.idle_add(lambda: not self.cancellable.is_cancelled() and self.info.set_text(text) and False)

            result = build_plan(self.window.settings, self.folder, self.remote, self.cancellable, progress, prepared)
            if not self.cancellable.is_cancelled():
                GLib.idle_add(lambda: self._show(*result) and False)
        except (GitError, GLib.Error) as err:
            message = getattr(err, "message", None) or str(err)
            GLib.idle_add(lambda: self._failed(message) and False)

    def _prepared(self, project, base, commits):
        self.project = project
        if base is None:  # first deployment: the comparison with the server can take a while
            self.uptodate_button.set_visible(True)
            self.info.set_text(_("First deployment: comparing the files tracked by Git with the server…"))

    def _mark_up_to_date(self):
        if self.project is None:
            return
        self.cancellable.cancel()
        remember(self.window.settings, self.folder, self.remote.get_uri(), self.project)
        self.window.toast(_("Marked as deployed ({sha}): next time, only new commits are sent.").format(
            sha=self.project.target[:7]))
        self.close()
        self.window.refresh_deploy_banner()

    def _failed(self, message):
        self.spinner.set_visible(False)
        self.info.set_text(message)

    def _show(self, project, plan, commits, base):
        self.project, self.plan = project, plan
        self.spinner.set_visible(False)
        target = project.target[:7]
        if base is None:
            info = _("First deployment: the files tracked by Git ({ref}, {sha}) are compared with the server "
                     "(size and date). Next time, only the files changed by your new commits will be sent.").format(
                ref=project.target_ref, sha=target)
        elif not plan.entries:
            info = _("Nothing to deploy: the server already has {ref} ({sha}).").format(ref=project.target_ref,
                                                                                        sha=target)
        else:
            info = ngettext("{n} commit pushed since the last deployment ({base} → {sha}, {ref}).",
                            "{n} commits pushed since the last deployment ({base} → {sha}, {ref}).",
                            len(commits)).format(n=len(commits), base=base[:7], sha=target, ref=project.target_ref)
        if not project.upstream:
            info += "\n" + _("This branch has no upstream on GitHub: the local branch “{branch}” is used.").format(
                branch=project.branch)
        if plan.errors:
            info += "\n" + plan.errors[0]
        self.info.set_text(info)
        if commits:
            self.commits_row.set_visible(True)
            self.commits_row.set_subtitle(ngettext("{n} commit", "{n} commits", len(commits)).format(n=len(commits)))
            for sha, subject in commits[:200]:
                row = Adw.ActionRow(title=GLib.markup_escape_text(subject), subtitle=sha)
                self.commits_row.add_row(row)
        for entry in plan.entries[:2000]:
            self.list.append(self._row(entry))
        self._update_send()

    def _row(self, entry):
        row = Adw.ActionRow(title=GLib.markup_escape_text(entry.path), subtitle=_kind_label(entry), title_lines=1,
                            activatable=True)
        check = Gtk.CheckButton(active=entry.selected, valign=Gtk.Align.CENTER)
        check.connect("toggled", lambda b: (setattr(entry, "selected", b.get_active()), self._update_send()))
        row.add_prefix(check)
        row.set_activatable_widget(check)
        icon = Gtk.Image(icon_name=_kind_icon(entry))
        if entry.kind == DELETED:
            icon.add_css_class("error")
        row.add_prefix(icon)
        return row

    def _update_send(self):
        chosen = self.plan.selected() if self.plan else []
        files = sum(1 for e in chosen if e.kind != DELETED)
        deletions = len(chosen) - files
        label = ngettext("Send {n} file", "Send {n} files", files).format(n=files)
        if deletions:
            label += " · " + ngettext("delete {n} item", "delete {n} items", deletions).format(n=deletions)
        # with nothing to send, the button still records the commit as deployed
        nothing = self.plan is not None and not self.plan.entries
        self.send_button.set_label(_("Mark as Deployed") if nothing else label)
        self.send_button.set_sensitive(bool(chosen) or nothing)

    def _send(self):
        from . import fileops

        window, project, plan = self.window, self.project, self.plan
        entries = plan.selected()
        folder, remote_uri = self.folder, self.remote.get_uri()
        self.close()

        def work(operation, errors):
            def progress(index, total, path):
                operation.update(detail=_("{current} of {total} — {name}").format(current=index + 1, total=total,
                                                                                 name=path),
                                 fraction=index / max(1, total))

            done, failed = apply(project, plan, entries, operation.cancellable, progress)
            errors.extend(failed)
            return done

        def finished(done, errors):
            if errors:
                window.toast(_("Some files could not be deployed: {error}").format(error=errors[0]))
                return
            remember(window.settings, folder, remote_uri, project)
            for pane in window.panes:
                if not pane.location.is_virtual and (pane.location.gfile.equal(plan.destination)
                                                     or pane.location.gfile.has_prefix(plan.destination)):
                    pane.reload()
            window.toast(ngettext("Deployed: {n} file ({sha})", "Deployed: {n} files ({sha})", done or 0)
                         .format(n=done or 0, sha=project.target[:7]))
            window.refresh_deploy_banner()

        fileops._run(window, _("Deploying to “{name}”").format(name=self.remote_title), work, finished)


def open_for(window, local_pane, remote_pane):
    from . import servers

    folder = local_pane.location.gfile.get_path() if not local_pane.location.is_virtual else None
    if not folder or remote_pane.location.is_virtual:
        window.toast(_("Open your project on one side and the server folder on the other."))
        return
    remote = remote_pane.location.gfile
    servers.ensure_mounted(window, remote, lambda: DeployDialog(window, folder, remote,
                                                                remote_pane.location.title).present(window))


def git_side(window):
    """(local_pane, remote_pane) when one side of the dual pane is in a Git repository."""
    if not window.dual_active():
        return None
    for local, remote in ((window.main_pane, window.side_pane), (window.side_pane, window.main_pane)):
        if local is None or remote is None or local.location.is_virtual or remote.location.is_virtual:
            continue
        gfile = local.location.gfile
        path = gfile.get_path()
        if not path or not gfile.is_native() or path.startswith(GVFS_ROOT) or remote.location.gfile.equal(gfile):
            continue  # never run git on a network folder (slow)
        if _cached_repo(path):
            return local, remote
    return None


_REPO_CACHE = {}


def _cached_repo(path):
    if path not in _REPO_CACHE:
        _REPO_CACHE[path] = repo_root(path) is not None
    return _REPO_CACHE[path]
