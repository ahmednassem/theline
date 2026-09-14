"""Embed real narration into every scenes-only demo.

Engines:
  eleven (default) :  ElevenLabs Brian with character timestamps, same as pi.
                     Needs quota: ~3500 credits for the 5 demos.
  edge             :  free Microsoft neural voice (no key, no quota).

The demo scenes already exist, so no server or LLM run is needed. Progress
is saved after every scene; safe to rerun after a quota error. pi.json is
never touched. --redo re-voices scenes that already have audio (use it to
swap edge voices for Brian once the ElevenLabs quota resets).

Usage: python tools/voice_demos.py [eleven|edge] [--redo]
"""
import asyncio
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent.parent
DEMOS = BASE / "UI" / "demos"
VOICE = "nPczCjzI2devNBz1zQrb"  # Brian :  same as pi
EDGE_VOICE = "en-US-ChristopherNeural"  # deep, calm :  the free stand-in


def api_key():
    for line in (BASE / ".env").read_text().splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no ELEVENLABS_API_KEY in .env")


def tts(text, key):
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}"
           "/with-timestamps?output_format=mp3_44100_128")
    body = json.dumps({"text": text, "model_id": "eleven_turbo_v2_5"}).encode()
    req = urllib.request.Request(url, data=body, headers={
        "xi-api-key": key, "Content-Type": "application/json"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            time.sleep(1.5)  # gentle on the free tier
            return {"audio_base64": d.get("audio_base64"),
                    "alignment": d.get("alignment")}
        except Exception as e:
            if attempt == 0:
                print(f"      tts error ({e}) :  waiting 20s and retrying")
                time.sleep(20)
            else:
                raise


def tts_edge(text):
    import edge_tts

    out = BASE / "data" / "edge_tmp.mp3"

    async def gen():
        await edge_tts.Communicate(text, EDGE_VOICE).save(str(out))

    asyncio.run(gen())
    b64 = base64.b64encode(out.read_bytes()).decode()
    out.unlink()
    return {"audio_base64": b64}  # no alignment: player paces by duration


def main():
    engine = "edge" if "edge" in sys.argv[1:] else "eleven"
    redo = "--redo" in sys.argv[1:]
    key = api_key() if engine == "eleven" else None
    for f in sorted(DEMOS.glob("*.json")):
        if f.name in ("index.json", "pi.json", "_capture.json"):
            continue
        demo = json.loads(f.read_text(encoding="utf-8"))
        segs = demo["segments"]
        todo = [s for s in segs if s.get("narration") and
                (redo or not (s.get("tts") or {}).get("audio_base64"))]
        if not todo:
            print(f"- {f.stem}: already voiced")
            continue
        print(f"- {f.stem}: voicing {len(todo)} scenes ({engine})...")
        for i, s in enumerate(todo):
            s["tts"] = tts(s["narration"], key) if engine == "eleven" \
                else tts_edge(s["narration"])
            print(f"    {i + 1}/{len(todo)} ok")
            f.write_text(json.dumps(demo), encoding="utf-8")  # save progress
        print(f"  saved {f.name} ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
