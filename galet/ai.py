"""Optional AI (off by default): natural-language search and tag suggestions.

Providers:
- **Ollama** (default): runs on the user's computer, nothing leaves it.
- **Claude** (Anthropic API, official ``anthropic`` Python SDK), **Mistral**, **Gemini**,
  **ChatGPT** (OpenAI): online services with an API key stored in the GNOME keyring.
- **Claude Code CLI** (``claude -p``) and **Gemini CLI** (``gemini -p``): reuse the
  user's existing subscription, no API key.

With online providers, file names and short document excerpts are sent to the
service: Settings shows a warning and asks for confirmation first.
"""

import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request

from gi.repository import GLib

from .i18n import N_
from .search import DATES, KINDS, document_text

EXCERPT_CHARS = 600
TIMEOUT = 90

PROVIDERS = {
    # id: label, kind, default model, needs key, local
    "ollama": {"label": N_("Ollama (local, private)"), "model": "llama3.2", "key": False, "local": True},
    "claude": {"label": "Claude (Anthropic API)", "model": "claude-opus-5-5", "key": True, "local": False},
    "mistral": {"label": "Mistral (API)", "model": "mistral-small-latest", "key": True, "local": False},
    "gemini": {"label": "Gemini (Google API)", "model": "gemini-flash-latest", "key": True, "local": False},
    "openai": {"label": "ChatGPT (OpenAI API)", "model": "gpt-5-mini", "key": True, "local": False},
    "claude-cli": {"label": N_("Claude Code (command line)"), "model": "", "key": False, "local": False},
    "gemini-cli": {"label": N_("Gemini CLI (command line)"), "model": "", "key": False, "local": False},
}
PROVIDER_ORDER = ("ollama", "claude", "mistral", "gemini", "openai", "claude-cli", "gemini-cli")
KEY_URLS = {
    "claude": "https://platform.claude.com/settings/keys",
    "mistral": "https://console.mistral.ai/api-keys",
    "gemini": "https://aistudio.google.com/apikey",
    "openai": "https://platform.openai.com/api-keys",
}
DEFAULT_OLLAMA_URL = "http://localhost:11434"


class AIError(Exception):
    pass


# ----------------------------------------------------------------- settings

def provider(settings):
    name = settings.get("ai_provider", "ollama")
    return name if name in PROVIDERS else "ollama"


def model(settings, name=None):
    name = name or provider(settings)
    models = settings.get("ai_models", {}) or {}
    return models.get(name) or PROVIDERS[name]["model"]


def set_model(settings, name, value):
    models = dict(settings.get("ai_models", {}) or {})
    models[name] = value.strip()
    settings.set("ai_models", models)


def is_cloud(name):
    return not PROVIDERS[name]["local"]


# ------------------------------------------------------- API keys (keyring)

def _schema():
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    return Secret, Secret.Schema.new("io.github.FloDerail.Galet.ApiKey", Secret.SchemaFlags.NONE,
                                     {"provider": Secret.SchemaAttributeType.STRING})


def get_key(name):
    try:
        secret, schema = _schema()
        return secret.password_lookup_sync(schema, {"provider": name}, None) or ""
    except Exception:  # noqa: BLE001  keyring unavailable (e.g. no Secret service)
        return ""


def set_key(name, key):
    secret, schema = _schema()
    if key:
        secret.password_store_sync(schema, {"provider": name}, secret.COLLECTION_DEFAULT,
                                   f"Galet – {name} API key", key, None)
    else:
        secret.password_clear_sync(schema, {"provider": name}, None)


# ----------------------------------------------------------------- requests

def _http(url, payload=None, headers=None, timeout=TIMEOUT):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:200]
        raise AIError(f"HTTP {err.code}: {detail}") from err
    except (urllib.error.URLError, OSError, ValueError) as err:
        raise AIError(str(getattr(err, "reason", err))) from err


def _parse_json(text):
    """JSON object from a model answer, tolerating ```json fences."""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("invalid answer")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as err:
        raise AIError("invalid answer") from err


def _need_key(name):
    key = get_key(name)
    if not key:
        raise AIError(f"no API key for {PROVIDERS[name]['label']} (Settings → AI)")
    return key


def _ask_ollama(settings, prompt, schema):
    url = (settings.get("ai_url") or DEFAULT_OLLAMA_URL).rstrip("/")
    answer = _http(url + "/api/generate", {"model": model(settings, "ollama"), "prompt": prompt, "stream": False,
                                           "format": schema, "options": {"temperature": 0.1}})
    return _parse_json(answer.get("response", ""))


def _ask_claude(settings, prompt, schema):
    try:
        import anthropic
    except ImportError as err:
        raise AIError("the “anthropic” Python package is missing: pip install --user anthropic") from err
    client = anthropic.Anthropic(api_key=get_key("claude") or None, timeout=TIMEOUT)
    try:
        response = client.beta.messages.create(
            model=model(settings, "claude"),
            max_tokens=4096,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # retry on another model if a safety classifier declines
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError as err:
        raise AIError("invalid Claude API key") from err
    except anthropic.RateLimitError as err:
        raise AIError("Claude rate limit reached, try again later") from err
    except anthropic.APIStatusError as err:
        raise AIError(f"Claude API error {err.status_code}: {err.message}") from err
    except anthropic.APIConnectionError as err:
        raise AIError("cannot reach the Claude API") from err
    if response.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _parse_json(text)


def _ask_mistral(settings, prompt, _schema_unused):
    answer = _http("https://api.mistral.ai/v1/chat/completions", {
        "model": model(settings, "mistral"),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
    }, {"Authorization": f"Bearer {_need_key('mistral')}"})
    return _parse_json(answer["choices"][0]["message"]["content"])


def _ask_openai(settings, prompt, _schema_unused):
    answer = _http("https://api.openai.com/v1/chat/completions", {
        "model": model(settings, "openai"),
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }, {"Authorization": f"Bearer {_need_key('openai')}"})
    return _parse_json(answer["choices"][0]["message"]["content"])


def _ask_gemini(settings, prompt, _schema_unused):
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{urllib.parse.quote(model(settings, 'gemini'))}:generateContent")
    answer = _http(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }, {"x-goog-api-key": _need_key("gemini")})
    try:
        text = answer["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as err:
        raise AIError("empty answer from Gemini") from err
    return _parse_json(text)


def _run_cli(args, prompt):
    from .sandbox import find_program

    command = find_program(args[0])
    if command is None:
        raise AIError(f"“{args[0]}” is not installed")
    try:
        completed = subprocess.run([*command, *args[1:]], input="", capture_output=True, text=True,
                                   timeout=TIMEOUT * 2, check=False)
    except subprocess.TimeoutExpired as err:
        raise AIError(f"{args[0]} did not answer in time") from err
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "error").strip()
        try:  # Claude Code reports errors as JSON: keep only the readable part
            data = json.loads(completed.stdout)
            message = str(data.get("result") or data.get("error") or message)
        except ValueError:
            pass
        raise AIError(message[:200])
    return completed.stdout


def _ask_claude_cli(_settings, prompt, schema):
    output = _run_cli(["claude", "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(schema),
                       "--restricted", "--no-session-persistence", "--disable-slash-commands"], prompt)
    try:
        data = json.loads(output)
    except ValueError as err:
        raise AIError("invalid answer from Claude Code") from err
    if data.get("is_error"):
        raise AIError(str(data.get("result") or "Claude Code error")[:200])
    return data.get("structured_output") or _parse_json(data.get("result", ""))


def _ask_gemini_cli(_settings, prompt, _schema_unused):
    output = _run_cli(["gemini", "-p", prompt + "\nAnswer with the JSON object only.", "--output-format", "json"],
                      prompt)
    try:
        data = json.loads(output)
        return _parse_json(data.get("response", ""))
    except ValueError:
        return _parse_json(output)


ASK = {"ollama": _ask_ollama, "claude": _ask_claude, "mistral": _ask_mistral, "gemini": _ask_gemini,
       "openai": _ask_openai, "claude-cli": _ask_claude_cli, "gemini-cli": _ask_gemini_cli}


def ask_json(settings, prompt, schema):
    return ASK[provider(settings)](settings, prompt, schema)


def ollama_models(settings):
    url = (settings.get("ai_url") or DEFAULT_OLLAMA_URL).rstrip("/")
    return [m.get("name", "") for m in _http(url + "/api/tags", timeout=5).get("models", [])]


def cli_available(name):
    program = {"claude-cli": "claude", "gemini-cli": "gemini"}.get(name)
    return program is None or shutil.which(program) is not None or os.path.exists("/.flatpak-info")


def run(work, done):
    """Run ``work()`` in a thread, then ``done(result, error)`` on the main loop."""

    def worker():
        try:
            result, error = work(), None
        except AIError as err:
            result, error = None, str(err)
        except Exception as err:  # noqa: BLE001  unexpected answer shape from a provider
            result, error = None, f"{type(err).__name__}: {err}"
        GLib.idle_add(lambda: done(result, error) and False)

    threading.Thread(target=worker, daemon=True).start()


# ------------------------------------------------------------------ search

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": [k for k, _l in KINDS]},
        "date": {"type": "string", "enum": [k for k, _l in DATES]},
        "content": {"type": "boolean"},
    },
    "required": ["text", "kind", "date", "content"],
    "additionalProperties": False,
}

SEARCH_PROMPT = """You turn a file search request into JSON. The request may be in any language.
Reply with JSON only, with these keys:
- "text": the main word(s) to look for (file name or document words), "" if none
- "kind": one of {kinds}
- "date": one of {dates}
- "content": true if the words should be searched inside documents, else false
Request: {request}"""


def parse_search(settings, request):
    data = ask_json(settings, SEARCH_PROMPT.format(
        kinds=", ".join(k for k, _l in KINDS), dates=", ".join(k for k, _l in DATES), request=request),
        SEARCH_SCHEMA)
    kind = data.get("kind") if data.get("kind") in [k for k, _l in KINDS] else "any"
    date = data.get("date") if data.get("date") in [k for k, _l in DATES] else "any"
    return {"text": str(data.get("text") or "").strip(), "kind": kind, "date": date,
            "content": bool(data.get("content"))}


# -------------------------------------------------------------------- tags

TAGS_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}},
                "required": ["name", "tags"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

TAGS_PROMPT = """Suggest tags to organise these files. Prefer the existing tags: {tags}.
You may propose at most one new short tag per file. Use the language of the existing tags.
Reply with JSON only: {{"files": [{{"name": "<file name>", "tags": ["tag", ...]}}]}} (0 to 3 tags per file).
Files:
{files}"""


def suggest_tags(settings, items, existing):
    lines = []
    for item in items[:20]:
        excerpt = ""
        if item.path and not item.is_dir:
            excerpt = " ".join(document_text(item.path, item.size).split())[:EXCERPT_CHARS]
        lines.append(f"- {item.name} ({item.kind}){': ' + excerpt if excerpt else ''}")
    data = ask_json(settings, TAGS_PROMPT.format(tags=", ".join(existing) or "(none)", files="\n".join(lines)),
                    TAGS_SCHEMA)
    entries = data.get("files", []) if isinstance(data, dict) else []
    if isinstance(entries, dict):  # tolerate {"name": [tags]} answers from free-form providers
        entries = [{"name": k, "tags": v} for k, v in entries.items()]
    by_name = {str(e.get("name", "")): e.get("tags", []) for e in entries if isinstance(e, dict)}
    result = {}
    for item in items:
        tags = by_name.get(item.name) or by_name.get(os.path.splitext(item.name)[0]) or []
        result[item] = [str(t).strip().replace(",", " ")[:30] for t in tags if str(t).strip()][:3]
    return result
