"""Generate a speech-like test WAV (syllable bursts with pauses) for the
speaking-state waveform, so milestone 1 needs no TTS keys."""
import math
import random
import struct
import wave
from pathlib import Path

SR = 22050
DUR = 7.0
OUT = Path(__file__).parent.parent / "UI" / "audio" / "test.wav"

random.seed(7)

# Build an amplitude envelope out of "syllables" and pauses.
events = []  # (start, end, amp)
t = 0.0
syll_in_word = 0
while t < DUR:
    length = random.uniform(0.07, 0.22)
    amp = random.uniform(0.45, 1.0)
    events.append((t, t + length, amp))
    t += length + random.uniform(0.02, 0.09)
    syll_in_word += 1
    if syll_in_word >= random.randint(5, 9):
        t += random.uniform(0.35, 0.75)  # sentence pause
        syll_in_word = 0


def envelope(time):
    for (s, e, a) in events:
        if s <= time <= e:
            # smooth in/out inside the syllable
            p = (time - s) / (e - s)
            return a * math.sin(math.pi * p) ** 0.7
    return 0.0


frames = bytearray()
phase = 0.0
for n in range(int(SR * DUR)):
    time = n / SR
    amp = envelope(time)
    f0 = 145 + 40 * math.sin(2 * math.pi * 1.7 * time)  # pitch wobble
    phase += 2 * math.pi * f0 / SR
    sig = (
        0.55 * math.sin(phase)
        + 0.25 * math.sin(2 * phase)
        + 0.12 * math.sin(3 * phase)
        + 0.10 * (random.random() * 2 - 1)  # breathiness
    )
    sample = int(max(-1, min(1, sig * amp * 0.8)) * 32767)
    frames += struct.pack("<h", sample)

OUT.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(OUT), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(bytes(frames))

print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
