// Director: plays a queue of segments {narration, ops[]} :  the exact format
// the server will stream later. Segments can be enqueued while playing
// (pipelining): the current segment performs while the next buffers.
//
// Narration: ElevenLabs via /api/tts, which returns audio + per-character
// timestamps :  every drawing op is anchored to a position in the sentence
// and fires exactly when the voice reaches it. If the endpoint is
// unavailable, falls back to the browser's built-in speech.
import { runOp } from "./dsl.js";
import { apiFetch } from "./api.js";

const CAPTURE = new URLSearchParams(location.search).has("capture");

let VOICE_ID = localStorage.getItem("line-voice-id") || "nPczCjzI2devNBz1zQrb"; // Brian

export function setVoiceId(id) {
  VOICE_ID = id;
  localStorage.setItem("line-voice-id", id);
}
export function getVoiceId() {
  return VOICE_ID;
}

async function fetchTTS(text) {
  const r = await apiFetch("api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, voice_id: VOICE_ID }),
  });
  if (!r.ok) throw new Error("tts " + r.status);
  return r.json(); // { audio_base64, alignment }
}

// --- browser TTS fallback ------------------------------------------------
let voice = null;
function pickVoice() {
  const vs = speechSynthesis.getVoices();
  voice =
    vs.find((v) => /^en/i.test(v.lang) && /natural|neural/i.test(v.name)) ||
    vs.find((v) => v.name === "Google US English") ||
    vs.find((v) => /^en[-_]US/i.test(v.lang)) ||
    vs.find((v) => /^en/i.test(v.lang)) ||
    null;
}
speechSynthesis.onvoiceschanged = pickVoice;
pickVoice();

export class Director {
  constructor(scene, audio, hooks = {}) {
    this.scene = scene;
    this.audio = audio;
    this.hooks = hooks; // { onState(mode), onDone() }
    this.queue = [];
    this.playing = false;
    this.finished = false;
    this._timeouts = [];
    this._gen = 0; // bumped on stop() to invalidate in-flight callbacks
  }

  enqueue(segment) {
    if (segment.tts && segment.tts.audio_base64) {
      // recorded demo: real narration audio + timestamps embedded, no API
      segment._tts = Promise.resolve(segment.tts);
    } else if (segment.narration) {
      // prefetch TTS so segments chain without gaps
      segment._tts = fetchTTS(segment.narration).catch(() => null);
    }
    if (this.paused && this._hold) {
      this._hold.segs.push(segment); // arrives while on hold :  plays on resume
      return;
    }
    this.queue.push(segment);
    if (!this.playing) this._next();
  }

  // A menu opened over the show: stop it but remember the current scene and
  // everything still queued, so closing the menu continues where it was.
  pauseHold() {
    if (!this.playing && !this.queue.length) return false;
    const hold = {
      segs: [this._currentSeg, ...this.queue].filter(Boolean),
      finished: this.finished,
    };
    this.stop();
    this._hold = hold;
    this.paused = true;
    return true;
  }

  resumeHold() {
    const h = this._hold;
    this.paused = false;
    this._hold = null;
    if (!h || !h.segs.length) return false;
    this.finished = false;
    h.segs.forEach((s) => this.enqueue(s));
    if (h.finished) this.end();
    return true;
  }

  end() {
    this.finished = true;
    if (!this.playing && this.queue.length === 0) this._allDone();
  }

  play(segments) {
    this.stop();
    this.finished = false;
    segments.forEach((s) => this.enqueue(s));
    this.end();
  }

  stop() {
    this._gen++;
    this._timeouts.forEach(clearTimeout);
    this._timeouts = [];
    speechSynthesis.cancel();
    this.audio?.stopNarration();
    this.queue = [];
    this.playing = false;
    this.finished = false;
    this.paused = false;
    this._hold = null;
    this._currentSeg = null;
    this.scene.clear();
    this.hooks.onState?.("idle");
  }

  _later(fn, ms) {
    this._timeouts.push(setTimeout(fn, ms));
  }

  _next() {
    const seg = this.queue.shift();
    if (!seg) {
      this.playing = false;
      if (this.finished) this._allDone();
      else this.hooks.onState?.("thinking"); // stream still producing
      return;
    }
    this.playing = true;
    this._currentSeg = seg;
    const gen = this._gen;

    const ops = (seg.ops || []).slice();
    // rule 11: flagged/filler scenes carry a visible lightweight note
    // (hidden in ?capture mode :  the recording stage stays clean)
    if ((seg.meta?.flagged || seg.meta?.filler) && !CAPTURE) {
      ops.push({
        op: "write", text: "~ unverified sketch", at: [1.15, -0.82],
        size: 0.05, color: "grey", id: "note-unverified",
      });
    }
    const text = seg.narration || "";
    // anchor each op to a fraction of the narration (spread over first 80%)
    const anchors = ops.map((op, i) => op.at_word ?? ((i + 0.4) / (ops.length + 0.4)) * 0.8);
    const fired = ops.map(() => false);
    let lastOpEnd = 0; // seconds from segment start when the last drawing finishes
    const t0 = performance.now();

    const fire = (i) => {
      if (fired[i] || gen !== this._gen) return;
      fired[i] = true;
      const d = runOp(this.scene, ops[i]);
      lastOpEnd = Math.max(lastOpEnd, (performance.now() - t0) / 1000 + d);
    };
    const fireUpTo = (frac) => ops.forEach((_, i) => { if (anchors[i] <= frac) fire(i); });

    let speechDone = false;
    let closed = false;
    const finishWhenReady = () => {
      if (closed || gen !== this._gen) return;
      if (!speechDone || !fired.every(Boolean)) return;
      closed = true;
      const wait = Math.max(0, lastOpEnd - (performance.now() - t0) / 1000) + 0.35;
      this._later(() => this._next(), wait * 1000);
    };
    const done = () => {
      if (gen !== this._gen) return;
      fireUpTo(1); // never leave ops unfired
      speechDone = true;
      finishWhenReady();
    };
    const poll = () => {
      finishWhenReady();
      if (!closed && gen === this._gen) this._later(poll, 250);
    };
    this._later(poll, 400);

    if (!text) {
      fireUpTo(1);
      speechDone = true;
      this._later(finishWhenReady, (lastOpEnd + 0.4) * 1000);
      return;
    }

    (seg._tts ?? fetchTTS(text).catch(() => null)).then(async (tts) => {
      if (gen !== this._gen) return;
      if (tts && tts.audio_base64) {
        try {
          const bytes = Uint8Array.from(atob(tts.audio_base64), (c) => c.charCodeAt(0));
          const { duration, ended } = await this.audio.playNarration(bytes.buffer);
          if (gen !== this._gen) { this.audio.stopNarration(); return; }
          // timing log for the offline video-capture tool (harmless otherwise)
          (window.__audioLog ??= []).push({ t: performance.now(), duration, text });
          this.hooks.onState?.("speaking");
          // character timestamps -> exact op fire times
          const times = tts.alignment?.character_start_times_seconds || [];
          const at = (frac) => {
            if (!times.length) return frac * duration;
            const idx = Math.min(times.length - 1, Math.floor(frac * times.length));
            return times[idx];
          };
          anchors.forEach((a, i) => this._later(() => fire(i), at(a) * 1000));
          ended.then(() => done());
          return;
        } catch { /* fall through to browser TTS */ }
      }
      this._speakBrowser(text, gen, anchors, fire, fireUpTo, done);
    });
  }

  _speakBrowser(text, gen, anchors, fire, fireUpTo, done) {
    if (gen !== this._gen) return;
    const u = new SpeechSynthesisUtterance(text);
    if (voice) u.voice = voice;
    u.rate = 1.0;
    u.onstart = () => gen === this._gen && this.hooks.onState?.("speaking");
    u.onboundary = (e) => {
      if (gen !== this._gen) return;
      if (e.charIndex != null && text.length) fireUpTo(e.charIndex / text.length);
    };
    u.onend = done;
    u.onerror = done;
    speechSynthesis.speak(u);
    // fallback for voices without boundary events: estimated pacing
    const est = Math.max(1.5, text.length * 0.062);
    anchors.forEach((a, i) => this._later(() => fire(i), a * est * 1000));
    this._later(done, est * 1000 + 4000); // hard safety if speech never ends
  }

  _allDone() {
    this._later(() => {
      this.scene.clear();
      this.hooks.onState?.("idle");
      this.hooks.onDone?.();
    }, 1200);
  }
}
