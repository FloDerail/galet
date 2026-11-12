"""Minimal gettext-compatible translation loader.

Translations live in ``po/<lang>.po`` and are read directly at startup, so the
app can run from a git checkout without a build step. Source strings are in
English; wrap every user-visible string with ``_()``.
"""

import ast
import os
from pathlib import Path

PO_DIR = Path(__file__).resolve().parent.parent / "po"


def _parse_po(text):
    catalog, entry, key = {}, {}, None

    def flush():
        if entry.get("msgid") and entry.get("msgstr"):
            catalog[entry["msgid"]] = entry["msgstr"]

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            entry, key, line = {}, "msgid", line[6:]
        elif line.startswith("msgstr "):
            key, line = "msgstr", line[7:]
        if key and line.startswith('"'):
            entry[key] = entry.get(key, "") + ast.literal_eval(line)
    flush()
    return catalog


def _languages():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var)
        if not value:
            continue
        langs = []
        for part in value.split(":"):
            code = part.split(".")[0].split("@")[0]
            if code and code not in ("C", "POSIX"):
                langs += [code, code.split("_")[0]]
        return langs
    return []


def _load():
    for lang in _languages():
        path = PO_DIR / f"{lang}.po"
        if path.is_file():
            try:
                return _parse_po(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, SyntaxError):
                return {}
    return {}


_catalog = _load()


def _(message):
    return _catalog.get(message, message)


def ngettext(singular, plural, n):
    return _(singular if n == 1 else plural)


def N_(message):
    """Mark a string for translation without translating it yet."""
    return message
