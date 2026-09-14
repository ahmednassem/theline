"""Record real answers into static demo files for the hosted version.

Runs each question through the LIVE local pipeline, then fetches the real
ElevenLabs narration (audio + character timestamps) for every scene and
embeds it into the segment. The result plays back identically to a live
answer :  with zero API keys on the hosting side.

Usage: python tools/record_demo.py   (server must be running on :8002)
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).parent.parent
DEMOS = BASE / "UI" / "demos"
CACHE = BASE / "data" / "demo_cache"  # asked scenes, so a TTS retry never re-asks
SERVER = "http://127.0.0.1:8002"
VOICE = "nPczCjzI2devNBz1zQrb"  # Brian

QUESTIONS = [
    {"slug": "pi", "question": "explain pi", "mode": "video"},
    {"slug": "derivative", "question": "what is a derivative", "mode": "video"},
    {"slug": "gravity", "question": "what is gravity", "mode": "video"},
    {"slug": "fourier", "question": "how do fourier series work", "mode": "video"},
    {"slug": "vector", "question": "what is a vector", "mode": "video"},
    {"slug": "quick-math", "question": "what is 12 times 12", "mode": "quick"},
]


def post(path, obj, timeout=600):
    r = urllib.request.Request(
        SERVER + path, data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(r, timeout=timeout)


def tts_for(text):
    """One narration -> audio+timestamps, gentle pacing + one retry."""
    for attempt in range(2):
        try:
            with post("/api/tts", {"text": text, "voice_id": VOICE}, timeout=120) as r:
                tts = json.loads(r.read())
            time.sleep(1.5)  # don't hammer the free tier
            return {"audio_base64": tts.get("audio_base64"),
                    "alignment": tts.get("alignment")}
        except Exception as e:
            if attempt == 0:
                print(f"      tts error ({e}) :  waiting 20s and retrying")
                time.sleep(20)
            else:
                raise


def get_segments(entry):
    """Asked scenes, from cache when available :  the LLM run happens once."""
    cache = CACHE / f"{entry['slug']}.json"
    if cache.exists():
        print(f"    scenes from cache")
        return json.loads(cache.read_text(encoding="utf-8"))
    t0 = time.time()
    segments = []
    with post("/api/ask", {
        "messages": [{"role": "user", "content": entry["question"]}],
        "mode": entry["mode"], "aspect": 1.78,
    }) as resp:
        for line in resp:
            seg = json.loads(line)
            segments.append(seg)
            print(f"    scene {seg['meta']['scene']}/{seg['meta']['of']} ({time.time()-t0:.0f}s)")
    if segments:
        CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(segments), encoding="utf-8")
    return segments


def record(entry):
    out = DEMOS / f"{entry['slug']}.json"
    if out.exists():
        print(f"- {entry['slug']}: exists, skip")
        return
    print(f"- {entry['slug']}: asking ({entry['mode']})...")
    segments = get_segments(entry)
    if not segments:
        print("  !! no segments :  skipping")
        return
    try:
        for i, seg in enumerate(segments):
            if not seg.get("narration"):
                continue
            print(f"    tts {i+1}/{len(segments)}")
            seg["tts"] = tts_for(seg["narration"])
    except Exception as e:
        # quota exhausted etc. :  ship scenes-only; the browser voice narrates.
        # Delete the demo file and rerun once credits exist: scenes are cached,
        # only the TTS calls happen again.
        print(f"    !! tts unavailable ({e}) :  saving scenes-only (browser voice)")
        for seg in segments:
            seg.pop("tts", None)
    DEMOS.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"question": entry["question"], "segments": segments}),
                   encoding="utf-8")
    print(f"  saved {out.name} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    for entry in QUESTIONS:
        try:
            record(entry)
        except Exception as e:
            print(f"  !! {entry['slug']} failed: {e}")
    index = [{"slug": q["slug"], "question": q["question"]} for q in QUESTIONS
             if (DEMOS / f"{q['slug']}.json").exists()]
    (DEMOS / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"index.json: {len(index)} demos")
