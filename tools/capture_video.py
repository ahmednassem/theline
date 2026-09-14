"""Auto-record any demo into an mp4 with real narration.

Usage:  python tools/capture_video.py [slug] [out.mp4]

How it syncs sound: Playwright's page video has no audio track. But the
director logs performance.now() whenever a narration clip starts
(window.__audioLog). Demos that carry embedded ElevenLabs mp3s (pi) play
those; demos recorded scenes-only get a free Microsoft Edge neural voice
generated per scene and embedded into a temporary demo file first. Either
way we capture the silent video, then lay each scene's mp3 at its logged
offset with ffmpeg's adelay and mux everything into one file.
"""
import asyncio
import base64
import http.server
import json
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

BASE = Path(__file__).parent.parent
UI = BASE / "UI"
WORK = BASE / "data" / "capture"
SLUG = sys.argv[1] if len(sys.argv) > 1 else "pi"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else \
    BASE.parent / "profile-website" / "public" / "theline" / f"{SLUG}-demo.mp4"
PORT = 8031  # static only :  no /api, so the page can't ask live
LEAD_IN = 1.5  # seconds of breathing line kept before the first narration
EDGE_VOICE = "en-US-ChristopherNeural"  # deep, calm :  close to Brian


def prepare():
    """Load the demo; voice unvoiced scenes with edge-tts. Returns
    (slug_to_play, segments, temp_file_or_None)."""
    WORK.mkdir(parents=True, exist_ok=True)
    demo = json.loads((UI / "demos" / f"{SLUG}.json").read_text(encoding="utf-8"))
    segs = demo["segments"]
    unvoiced = [s for s in segs
                if s.get("narration") and not (s.get("tts") or {}).get("audio_base64")]
    if not unvoiced:
        return SLUG, segs, None

    import edge_tts

    async def voice_all():
        for i, s in enumerate(unvoiced):
            f = WORK / f"edge{i}.mp3"
            await edge_tts.Communicate(s["narration"], EDGE_VOICE).save(str(f))
            s["tts"] = {"audio_base64": base64.b64encode(f.read_bytes()).decode()}
            print(f"voiced scene {i + 1}/{len(unvoiced)}")

    asyncio.run(voice_all())
    tmp = UI / "demos" / "_capture.json"
    tmp.write_text(json.dumps(demo), encoding="utf-8")
    return "_capture", segs, tmp


def serve_static():
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(UI))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def capture(play_slug):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        # slightly wider than the demo's recorded 1.78 aspect, so text placed
        # near the screen edge never clips; ?capture hides icons/hint/input
        ctx = browser.new_context(
            viewport={"width": 1400, "height": 720},
            record_video_dir=str(WORK),
            record_video_size={"width": 1400, "height": 720},
        )
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{PORT}/?capture")
        # note the arrow wrapper: a bare expression that evaluates to a
        # function would be *invoked* by wait_for_function
        page.wait_for_function("() => !!(window.__line && window.__line.playDemo)")
        time.sleep(3.0)  # font + demo index + first breathing moments
        page.evaluate(f"window.__line.playDemo('{play_slug}')")
        print("playing the demo...")
        page.wait_for_function("window.__lineDone === true", timeout=8 * 60 * 1000)
        time.sleep(1.5)  # let the closing fade finish
        audio_log = page.evaluate("window.__audioLog || []")
        video = page.video
        ctx.close()  # flushes the recording
        raw = Path(video.path())
        browser.close()
    print(f"captured {raw.name}, {len(audio_log)} narration starts logged")
    return raw, audio_log


def extract_audio(segs):
    files = []
    for i, seg in enumerate(segs):
        b64 = (seg.get("tts") or {}).get("audio_base64")
        if not b64:
            files.append(None)
            continue
        f = WORK / f"seg{i}.mp3"
        f.write_bytes(base64.b64decode(b64))
        files.append(f)
    return files


def mux(raw, audio_log, seg_files, out):
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    # match logged starts to segment files in order (both are scene order)
    voiced = [f for f in seg_files if f is not None]
    if len(audio_log) != len(voiced):
        print(f"warning: {len(audio_log)} starts vs {len(voiced)} clips :  using min")
    pairs = list(zip(audio_log, voiced))
    if not pairs:
        print("no narration timing captured :  shipping the video silent")
        subprocess.run([ffmpeg, "-y", "-i", str(raw),
                        "-c:v", "libx264", "-crf", "23", "-pix_fmt", "yuv420p",
                        "-an", str(out)], check=True)
        return

    t0 = pairs[0][0]["t"] / 1000.0  # first narration, in video seconds
    trim = max(0.0, t0 - LEAD_IN)

    cmd = [ffmpeg, "-y", "-ss", f"{trim:.3f}", "-i", str(raw)]
    for _, f in pairs:
        cmd += ["-i", str(f)]
    parts, labels = [], []
    for i, (log, _) in enumerate(pairs):
        delay = max(0, int((log["t"] / 1000.0 - trim) * 1000))
        parts.append(f"[{i + 1}:a]adelay={delay}|{delay}[a{i}]")
        labels.append(f"[a{i}]")
    parts.append(f"{''.join(labels)}amix=inputs={len(pairs)}:normalize=0[aout]")
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "libx264", "-crf", "23", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    play_slug, segs, tmp = prepare()
    httpd = serve_static()
    try:
        raw, audio_log = capture(play_slug)
    finally:
        httpd.shutdown()
        if tmp:
            tmp.unlink(missing_ok=True)
    seg_files = extract_audio(segs)
    mux(raw, audio_log, seg_files, OUT)
    print(f"done: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
