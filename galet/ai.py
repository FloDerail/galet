"""Optional local AI (off by default): natural-language search and tag suggestions.

Everything runs on the user's computer through Ollama (https://ollama.com):
no file name or content is ever sent to an online service.
"""

import json
import os
import threading
import urllib.error
import urllib.request

from gi.repository import GLib

from .search import DATES, KINDS, document_text

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
EXCERPT_CHARS = 600


class AIError(Exception):
    pass


def _url(settings):
    return (settings.get("ai_url") or DEFAULT_URL).rstrip("/")


def _request(url, payload=None, timeout=90):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise AIError(str(getattr(err, "reason", err))) from err


def models(settings):
    """Names of the models installed in Ollama."""
    return [m.get("name", "") for m in _request(_url(settings) + "/api/tags", timeout=5).get("models", [])]


def ask_json(settings, prompt):
    answer = _request(_url(settings) + "/api/generate", {
        "model": settings.get("ai_model") or DEFAULT_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1},
    })
    try:
        return json.loads(answer.get("response", "{}"))
    except ValueError as err:
        raise AIError("invalid answer") from err


def run(work, done):
    """Run ``work()`` in a thread, then ``done(result, error)`` on the main loop."""

    def worker():
        try:
            result, error = work(), None
        except AIError as err:
            result, error = None, str(err)
        GLib.idle_add(lambda: done(result, error) and False)

    threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ search

SEARCH_PROMPT = """You turn a file search request into JSON. The request may be in any language.
Reply with JSON only, with these keys:
- "text": the main word(s) to look for (file name or document words), "" if none
- "kind": one of {kinds}
- "date": one of {dates}
- "content": true if the words should be searched inside documents, else false
Request: {request}"""


def parse_search(settings, request):
    data = ask_json(settings, SEARCH_PROMPT.format(
        kinds=", ".join(k for k, _l in KINDS), dates=", ".join(k for k, _l in DATES), request=request))
    kind = data.get("kind") if data.get("kind") in [k for k, _l in KINDS] else "any"
    date = data.get("date") if data.get("date") in [k for k, _l in DATES] else "any"
    return {"text": str(data.get("text") or "").strip(), "kind": kind, "date": date,
            "content": bool(data.get("content"))}


# -------------------------------------------------------------------- tags

TAGS_PROMPT = """Suggest tags to organise these files. Prefer the existing tags: {tags}.
You may propose at most one new short tag per file. Use the language of the existing tags.
Reply with JSON only: {{"files": {{"<file name>": ["tag", ...]}}}} (0 to 3 tags per file).
Files:
{files}"""


def suggest_tags(settings, items, existing):
    lines = []
    for item in items[:20]:
        excerpt = ""
        if item.path and not item.is_dir:
            excerpt = " ".join(document_text(item.path, item.size).split())[:EXCERPT_CHARS]
        lines.append(f"- {item.name} ({item.kind}){': ' + excerpt if excerpt else ''}")
    data = ask_json(settings, TAGS_PROMPT.format(tags=", ".join(existing) or "(none)", files="\n".join(lines)))
    files = data.get("files", {}) if isinstance(data, dict) else {}
    result = {}
    for item in items:
        tags = files.get(item.name) or files.get(os.path.splitext(item.name)[0]) or []
        result[item] = [str(t).strip().replace(",", " ")[:30] for t in tags if str(t).strip()][:3]
    return result
