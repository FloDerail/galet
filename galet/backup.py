"""Back up and restore Galet's configuration in a single JSON file.

Contents: settings, tag definitions, tags of files and folders, folder colours,
sidebar favourites and AI photo descriptions. API keys are never included (they
stay in the GNOME keyring). Paths are adapted when the home folder differs
(another computer or user name).
"""

import json
import os
import time
from pathlib import Path

from gi.repository import Gio, GLib

from . import __version__

FORMAT = "galet-backup"
FORMAT_VERSION = 1
SECTIONS = ("settings", "tags", "file_tags", "folder_colors", "bookmarks", "photo_descriptions")
SKIPPED_SETTINGS = ("window_size",)
BOOKMARKS = Path(GLib.get_user_config_dir()) / "gtk-3.0" / "bookmarks"


class BackupError(Exception):
    pass


def default_file_name():
    return time.strftime("Galet-sauvegarde-%Y-%m-%d.json")


# ------------------------------------------------------------------ export

def _read_bookmarks():
    try:
        return [line for line in BOOKMARKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return []


def collect(app, sections=SECTIONS):
    """Gather the selected sections into a dict ready to be saved."""
    from . import folders
    from .photoindex import PHOTO_INDEX

    data = {"format": FORMAT, "version": FORMAT_VERSION, "galet": __version__,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "home": GLib.get_home_dir()}
    tagstore = app.tagstore
    if "settings" in sections:
        data["settings"] = {k: v for k, v in app.settings.data.items() if k not in SKIPPED_SETTINGS}
    if "tags" in sections:
        data["tags"] = [dict(t) for t in tagstore.tags]
    if "file_tags" in sections:
        file_tags = {}
        for path in list(tagstore._index):
            if os.path.lexists(path):
                tags = tagstore.read(path)
                if tags:
                    file_tags[path] = tags
        data["file_tags"] = file_tags
    if "folder_colors" in sections:
        data["folder_colors"] = folders.all_colored()
    if "bookmarks" in sections:
        data["bookmarks"] = _read_bookmarks()
    if "photo_descriptions" in sections:
        PHOTO_INDEX.count()  # loads the index
        with PHOTO_INDEX._lock:
            data["photo_descriptions"] = dict(PHOTO_INDEX._entries or {})
    return data


def summary(data):
    """Counts shown before importing."""
    return {
        "settings": len(data.get("settings", {})),
        "tags": len(data.get("tags", [])),
        "file_tags": len(data.get("file_tags", {})),
        "folder_colors": len(data.get("folder_colors", {})),
        "bookmarks": len(data.get("bookmarks", [])),
        "photo_descriptions": len(data.get("photo_descriptions", {})),
    }


def write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as err:
        raise BackupError(str(err)) from err
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BackupError("not a Galet backup file")
    if data.get("version", 0) > FORMAT_VERSION:
        raise BackupError("this backup was made by a newer version of Galet")
    return data


# ----------------------------------------------------------------- restore

def _remapper(data):
    old, new = data.get("home") or "", GLib.get_home_dir()

    def remap(path):
        if old and old != new and (path == old or path.startswith(old.rstrip("/") + "/")):
            return new + path[len(old):]
        return path

    def remap_uri(line):
        uri, sep, label = line.partition(" ")
        if uri.startswith("file://"):
            local = Gio.File.new_for_uri(uri).get_path()
            if local:
                uri = Gio.File.new_for_path(remap(local)).get_uri()
        return uri + sep + label

    return remap, remap_uri


def restore(app, data, sections=SECTIONS):
    """Apply a backup. Settings are replaced; tags, colours, favourites are merged."""
    from . import folders
    from .photoindex import PHOTO_INDEX

    remap, remap_uri = _remapper(data)
    report = {name: 0 for name in SECTIONS}
    tagstore = app.tagstore

    if "settings" in sections:
        for key, value in data.get("settings", {}).items():
            if key not in SKIPPED_SETTINGS:
                app.settings.set(key, value)
                report["settings"] += 1
    if "tags" in sections:
        for tag in data.get("tags", []):
            name, color = str(tag.get("name", "")).strip(), tag.get("color")
            if not name:
                continue
            if any(t["name"] == name for t in tagstore.tags):
                if color and tagstore.color_of(name) != color:
                    tagstore.set_color(name, color)
            else:
                tagstore.add_tag(name, color)
            report["tags"] += 1
    if "file_tags" in sections:
        for path, tags in data.get("file_tags", {}).items():
            path = remap(path)
            if not os.path.lexists(path):
                continue
            current = tagstore.read(path)
            merged = current + [t for t in tags if t not in current]
            if merged != current:
                try:
                    tagstore.write(path, merged)
                except OSError:
                    continue
            report["file_tags"] += 1
    if "folder_colors" in sections:
        for path, color in data.get("folder_colors", {}).items():
            path = remap(path)
            if os.path.isdir(path):
                try:
                    folders.set_color(Gio.File.new_for_path(path), color)
                    report["folder_colors"] += 1
                except GLib.Error:
                    pass
    if "bookmarks" in sections:
        lines = _read_bookmarks()
        existing = {line.split(" ", 1)[0] for line in lines}
        for line in data.get("bookmarks", []):
            line = remap_uri(line)
            if line.split(" ", 1)[0] not in existing:
                lines.append(line)
                existing.add(line.split(" ", 1)[0])
                report["bookmarks"] += 1
        BOOKMARKS.parent.mkdir(parents=True, exist_ok=True)
        BOOKMARKS.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    if "photo_descriptions" in sections:
        for path, entry in data.get("photo_descriptions", {}).items():
            path = remap(path)
            if os.path.exists(path) and isinstance(entry, dict):
                PHOTO_INDEX.count()
                with PHOTO_INDEX._lock:
                    PHOTO_INDEX._entries[path] = entry
                    PHOTO_INDEX._folded[path] = PHOTO_INDEX._fold_entry(entry)
                report["photo_descriptions"] += 1
        PHOTO_INDEX.save()
    tagstore.flush()
    return report
