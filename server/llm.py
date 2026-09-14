"""LLM adapter :  the pipeline never knows which brand is underneath.

complete(system, messages, max_tokens) dispatches on the runtime config:
  claude  -> Anthropic messages API
  openai  -> any OpenAI-compatible /chat/completions (OpenAI, OpenRouter,
             Groq, local Ollama, ...) via the configurable base URL
"""
import json
import threading
import urllib.request

from . import config

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_LIMITER = threading.Semaphore(2)  # shared: planner + create + llm-check


def _get(cfg, field):
    """Per-request override (browser-supplied key) wins over stored config."""
    if cfg and cfg.get(field):
        return cfg[field]
    return config.get(field)


def configured(cfg=None):
    """True when the selected provider has an API key."""
    return bool(_get(cfg, "llm_api_key"))


def _claude(system, messages, max_tokens, cfg):
    body = json.dumps({
        "model": _get(cfg, "llm_model"),
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_URL, data=body,
        headers={
            "x-api-key": _get(cfg, "llm_api_key"),
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    with _LIMITER:
        with urllib.request.urlopen(req, timeout=120) as resp:
            obj = json.loads(resp.read())
    return "".join(b.get("text", "") for b in obj.get("content", []) if b.get("type") == "text")


def _openai(system, messages, max_tokens, cfg):
    base = _get(cfg, "llm_base_url").rstrip("/")
    body = json.dumps({
        "model": _get(cfg, "llm_model"),
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}] + messages,
    }).encode()
    req = urllib.request.Request(
        base + "/chat/completions", data=body,
        headers={
            "Authorization": "Bearer " + _get(cfg, "llm_api_key"),
            "Content-Type": "application/json",
        },
    )
    with _LIMITER:
        with urllib.request.urlopen(req, timeout=120) as resp:
            obj = json.loads(resp.read())
    choices = obj.get("choices") or []
    return choices[0].get("message", {}).get("content", "") if choices else ""


def complete(system, messages, max_tokens=2500, cfg=None):
    if not configured(cfg):
        raise RuntimeError("no LLM API key configured :  set it in settings")
    if _get(cfg, "llm_provider") == "openai":
        return _openai(system, messages, max_tokens, cfg)
    return _claude(system, messages, max_tokens, cfg)
