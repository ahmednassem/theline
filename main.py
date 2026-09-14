"""The Line :  server entry point.

- Static file server for the UI
- /api/tts: ElevenLabs proxy (audio + character timestamps for sync)
- /api/ask: pipeline v2 (plan-first + neuro-symbolic) :  streams checked
  scenes as NDJSON while later scenes are still being generated.
"""
import json
import os
import urllib.request
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).parent


def load_env():
    p = BASE / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()

from server import config, llm, pipeline  # noqa: E402 :  needs env loaded first

app = FastAPI(title="The Line")


# ------------------------------------------------------------------ config
# API keys are editable from the in-app settings :  but only for localhost
# callers, since the keys pass in clear text.
def _require_localhost(request: Request):
    # behind nginx every connection comes from 127.0.0.1 :  the proxy stamps
    # the visitor's real address in X-Real-IP, which wins when present
    host = (request.headers.get("x-real-ip", "").strip()
            or (request.client.host if request.client else ""))
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(403, "config is only editable from localhost")


# Bring-your-own-key: the hosted server stores no keys. The browser sends the
# visitor's keys as headers on each request; they are used transiently and
# never persisted or logged.
_HEADER_FIELDS = {
    "x-llm-key": "llm_api_key",
    "x-llm-provider": "llm_provider",
    "x-llm-model": "llm_model",
    "x-llm-base-url": "llm_base_url",
    "x-eleven-key": "eleven_api_key",
}


def _overrides(request: Request):
    cfg = {}
    for header, field in _HEADER_FIELDS.items():
        v = request.headers.get(header, "").strip()
        if v:
            cfg[field] = v
    return cfg


def _eleven_key(request: Request):
    return _overrides(request).get("eleven_api_key") or config.get("eleven_api_key")


class ConfigUpdate(BaseModel):
    llm_provider: str = ""
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    eleven_api_key: str = ""
    clear: list = []  # field names to remove outright


@app.get("/api/config")
def get_config(request: Request):
    _require_localhost(request)
    return {
        "llm_provider": config.get("llm_provider"),
        "llm_model": config.get("llm_model"),
        "llm_base_url": config.get("llm_base_url"),
        "llm_api_key": config.masked(config.get("llm_api_key")),
        "eleven_api_key": config.masked(config.get("eleven_api_key")),
    }


@app.post("/api/config")
def set_config(req: ConfigUpdate, request: Request):
    _require_localhost(request)
    partial = {k: v for k, v in req.dict().items()
               if k != "clear" and isinstance(v, str) and v.strip()}
    if partial.get("llm_provider") and partial["llm_provider"] not in ("claude", "openai"):
        raise HTTPException(400, "provider must be claude or openai")
    config.update(partial, clear=[c for c in req.clear if isinstance(c, str)])
    return get_config(request)


@app.get("/api/health")
def health():
    """Lets the UI know whether live asking works without visitor keys."""
    return {"server": True, "llm_configured": llm.configured()}


@app.post("/api/check_keys")
def check_keys(request: Request, body: ConfigUpdate):
    """Validate keys (from the request body, falling back to stored config)
    with real, minimal API calls. Returns a short status per key."""
    cfg = {k: v for k, v in body.dict().items()
           if k != "clear" and isinstance(v, str) and v.strip()}

    if llm.configured(cfg):
        try:
            llm.complete("Reply with the single word: ok",
                         [{"role": "user", "content": "ok?"}],
                         max_tokens=8, cfg=cfg)
            llm_status = "ok"
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read()).get("error", {}).get("message", "")[:80]
            except Exception:
                pass
            llm_status = f"error {e.code}" + (f": {detail}" if detail else "")
        except Exception as e:
            llm_status = f"error: {str(e)[:80]}"
    else:
        llm_status = "no key"

    voice_key = cfg.get("eleven_api_key") or config.get("eleven_api_key")
    if voice_key:
        voice_status = _check_voice_key(voice_key)
    else:
        voice_status = "no key"

    return {"llm": llm_status, "voice": voice_status}


def _check_voice_key(key):
    """Subscription endpoint when permitted (shows chars left); restricted
    TTS-only keys get a real 1-character TTS probe instead."""
    try:
        r = urllib.request.Request(
            "https://api.elevenlabs.io/v1/user/subscription",
            headers={"xi-api-key": key},
        )
        with urllib.request.urlopen(r, timeout=30) as resp:
            sub = json.loads(resp.read())
        left = sub.get("character_limit", 0) - sub.get("character_count", 0)
        return f"ok - {max(0, left)} chars left"
    except urllib.error.HTTPError as e:
        try:
            restricted = b"missing_permissions" in e.read()
        except Exception:
            restricted = False
        if not restricted:
            return f"error {e.code}"
    except Exception as e:
        return f"error: {str(e)[:80]}"
    # key exists but can't read the account :  probe TTS itself (1 char)
    try:
        body = json.dumps({"text": ".", "model_id": "eleven_turbo_v2_5"}).encode()
        r = urllib.request.Request(
            "https://api.elevenlabs.io/v1/text-to-speech/nPczCjzI2devNBz1zQrb"
            "?output_format=mp3_22050_32",
            data=body, headers={"xi-api-key": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(r, timeout=30) as resp:
            resp.read()
        return "ok"
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("detail", {}).get("status", "")
        except Exception:
            pass
        return f"error {e.code}" + (f": {detail}" if detail else "")
    except Exception as e:
        return f"error: {str(e)[:80]}"


# premade voices verified to work on this account (free plan blocks
# legacy/library voices like Rachel)
VOICES = [
    {"name": "Brian", "id": "nPczCjzI2devNBz1zQrb"},
    {"name": "Sarah", "id": "EXAVITQu4vr4xnSDxMaL"},
    {"name": "George", "id": "JBFqnCBsd6RMkjVDRZzb"},
    {"name": "Laura", "id": "FGY2WhTYpPnrIDTdsKH5"},
    {"name": "Callum", "id": "N2lVS1w4EtoT3dr4eOWO"},
    {"name": "River", "id": "SAz9YHcvj6GT2YYXdXww"},
    {"name": "Liam", "id": "TX3LPaxmHKxFdv7VOQHJ"},
    {"name": "Alice", "id": "Xb7hH8MSUJpSbSDYk0k2"},
    {"name": "Matilda", "id": "XrExE9yKIg1WjnnlVkGX"},
    {"name": "Will", "id": "bIHbv24MWmeRgasZH58o"},
    {"name": "Jessica", "id": "cgSgspJ2msm6clMCkdW9"},
    {"name": "Eric", "id": "cjVigY5qzO86Huf0OWal"},
    {"name": "Chris", "id": "iP95p4xoKVk53GoZ742B"},
    {"name": "Daniel", "id": "onwK4e9ZLuTAKqWW03F9"},
    {"name": "Lily", "id": "pFZP5JQG7iQjIQuC4Bku"},
    {"name": "Bill", "id": "pqHfZKP75CvOlQylNhV4"},
]


@app.get("/api/voices")
def voices():
    return VOICES


SAMPLES = BASE / "data" / "samples"


@app.get("/api/voice_sample/{voice_id}")
def voice_sample(voice_id: str, request: Request):
    """Short spoken sample per voice, generated once and cached on disk."""
    entry = next((v for v in VOICES if v["id"] == voice_id), None)
    if not entry:
        raise HTTPException(404, "unknown voice")
    SAMPLES.mkdir(parents=True, exist_ok=True)
    f = SAMPLES / f"{voice_id}.mp3"
    if not f.exists():
        key = _eleven_key(request)
        if not key:
            raise HTTPException(503, "voice API key not configured :  set it in settings")
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            "?output_format=mp3_44100_128"
        )
        body = json.dumps({
            "text": f"Hey, I'm {entry['name']}. This is how I sound.",
            "model_id": "eleven_turbo_v2_5",
        }).encode()
        r = urllib.request.Request(
            url, data=body,
            headers={"xi-api-key": key, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(r, timeout=60) as resp:
            f.write_bytes(resp.read())
    return Response(content=f.read_bytes(), media_type="audio/mpeg")


class TTSRequest(BaseModel):
    text: str
    voice_id: str = "nPczCjzI2devNBz1zQrb"  # Brian


@app.post("/api/tts")
def tts(req: TTSRequest, request: Request):
    """Text -> ElevenLabs audio + per-character timestamps."""
    key = _eleven_key(request)
    if not key:
        raise HTTPException(503, "voice API key not configured :  set it in settings")
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{req.voice_id}"
        "/with-timestamps?output_format=mp3_44100_128"
    )
    body = json.dumps({"text": req.text, "model_id": "eleven_turbo_v2_5"}).encode()
    r = urllib.request.Request(
        url, data=body,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, f"ElevenLabs: {e.read()[:300]!r}")


class AskRequest(BaseModel):
    messages: list  # full chat history: [{"role": "user"|"assistant", "content": str}]
    mode: str = "auto"  # quick (1-3 scenes) | video (4-10) | auto (planner decides)
    depth: str = "auto"  # auto | surface | deep | detailed
    aspect: float = 1.78  # the caller's real window width/height


@app.post("/api/ask")
def ask(req: AskRequest, request: Request):
    cfg = _overrides(request)
    if not llm.configured(cfg):
        raise HTTPException(503, "LLM API key not configured :  set it in settings")
    if not req.messages:
        raise HTTPException(400, "empty messages")
    mode = req.mode if req.mode in ("quick", "video", "auto") else "auto"
    depth = req.depth if req.depth in ("auto", "surface", "deep", "detailed") else "auto"
    aspect = max(1.0, min(2.4, req.aspect or 1.78))
    return StreamingResponse(pipeline.run(req.messages, mode, depth, aspect, cfg=cfg),
                             media_type="application/x-ndjson")


app.mount("/", StaticFiles(directory=BASE / "UI", html=True), name="ui")


def start():
    host = os.environ.get("LINE_HOST", "127.0.0.1")
    port = int(os.environ.get("LINE_PORT", "8002"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start()
