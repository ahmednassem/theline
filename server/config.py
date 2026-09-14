"""Runtime config: .env values as defaults, data/config.json on top.

Keys saved from the settings UI land in data/config.json (gitignored) and
take effect immediately :  no server restart needed.
"""
import json
import threading
from pathlib import Path

import os

BASE = Path(__file__).parent.parent
CONFIG_FILE = BASE / "data" / "config.json"
_LOCK = threading.Lock()

# field -> .env fallback variable
FIELDS = {
    "llm_provider": None,       # claude | openai
    "llm_model": "LLM_MODEL",
    "llm_base_url": None,       # openai-compatible base, e.g. https://api.openai.com/v1
    "llm_api_key": "ANTHROPIC_API_KEY",
    "eleven_api_key": "ELEVENLABS_API_KEY",
}

DEFAULTS = {
    "llm_provider": "claude",
    "llm_model": "claude-sonnet-4-6",
    "llm_base_url": "https://api.openai.com/v1",
}


def _file_values():
    if not CONFIG_FILE.exists():
        return {}
    try:
        obj = json.loads(CONFIG_FILE.read_text())
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def get(field):
    """config.json > .env > built-in default."""
    vals = _file_values()
    v = vals.get(field)
    if v:
        return str(v)
    env_var = FIELDS.get(field)
    if env_var and os.environ.get(env_var):
        return os.environ[env_var]
    return DEFAULTS.get(field, "")


def update(partial, clear=None):
    """Persist the given fields (unknown fields ignored, empty = no change).

    Fields listed in `clear` are removed outright :  including masking any
    .env fallback, so "clear" really means "no key" afterwards.
    """
    with _LOCK:
        vals = _file_values()
        for k, v in (partial or {}).items():
            if k in FIELDS and isinstance(v, str) and v.strip():
                vals[k] = v.strip()
        for k in clear or []:
            if k in FIELDS:
                vals.pop(k, None)
                env_var = FIELDS.get(k)
                if env_var:
                    os.environ.pop(env_var, None)
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(vals, indent=2))
    return vals


def masked(value):
    """Show enough of a key to recognize it, never the whole thing."""
    if not value:
        return ""
    if len(value) <= 12:
        return value[:2] + "..." + value[-2:]
    return value[:7] + "..." + value[-4:]
