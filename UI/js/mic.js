// Voice input :  a stroke-drawn microphone in the bottom-right corner.
// While listening, the real mic signal drives the line (it waves along with
// YOUR voice), and the browser's speech recognition turns speech into the
// question. Works in Chrome/Edge on localhost or https.

function micPolys(cx, cy, r) {
  const polys = [];
  // capsule body
  const w = 0.34 * r, top = cy + 1.05 * r, bot = cy + 0.1 * r;
  const body = [];
  for (let i = 0; i <= 12; i++) { // top half-circle
    const a = Math.PI - (i / 12) * Math.PI;
    body.push([cx + w * Math.cos(a), top + w * Math.sin(a)]);
  }
  body.push([cx + w, bot]);
  for (let i = 0; i <= 12; i++) { // bottom half-circle
    const a = -(i / 12) * Math.PI;
    body.push([cx + w * Math.cos(a), bot + w * Math.sin(a)]);
  }
  body.push([cx - w, top]);
  polys.push(body);
  // holder arc: a "U" under the capsule, opening upward
  const hr = 0.68 * r, arc = [];
  for (let i = 0; i <= 16; i++) {
    const a = Math.PI + (i / 16) * Math.PI; // 180deg -> 360deg = lower half
    arc.push([cx + hr * Math.cos(a), bot + 0.1 * r + hr * Math.sin(a)]);
  }
  polys.push(arc);
  // stand + base
  polys.push([[cx, bot - hr - 0.1 * r], [cx, bot - hr - 0.45 * r]]);
  polys.push([[cx - 0.4 * r, bot - hr - 0.45 * r], [cx + 0.4 * r, bot - hr - 0.45 * r]]);
  return polys;
}

const DIM = 0.35, LIT = 0.95;
const LIVE_COLOR = 0xfc6255; // red while listening

export class Mic {
  constructor(line, ui, audio, hooks) {
    this.line = line;
    this.ui = ui;
    this.audio = audio;
    this.hooks = hooks; // { onInterim, onFinal, onStateChange, onError }
    this.listening = false;
    this.rect = null;
    this._rec = null;
    this._final = "";
    window.addEventListener("resize", () => setTimeout(() => this.drawIcon(), 60));
  }

  get supported() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  }

  drawIcon() {
    const cx = this.line.aspect - 0.14, cy = -0.84, r = 0.05;
    this.ui.draw("mic", micPolys(cx, cy, r), {
      color: this.listening ? LIVE_COLOR : 0xffffff,
    });
    this._setOpacity(this.listening ? 1 : DIM);
    const pad = 0.07;
    this.rect = { x0: cx - pad, x1: cx + pad, y0: cy - pad, y1: cy + pad * 1.4 };
  }

  _setOpacity(o) {
    const g = this.ui.strokes.get("mic");
    if (g) g.forEach((s) => { if (!s.dead) s.opacity = o; });
  }

  _hit(x, y) {
    const r = this.rect;
    return r && x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
  }

  click(x, y) {
    if (!this._hit(x, y)) return false;
    this.toggle();
    return true;
  }

  move(x, y) {
    const on = this._hit(x, y);
    if (!this.listening) this._setOpacity(on ? LIT : DIM);
    return on;
  }

  toggle() {
    this.listening ? this.stop() : this.start();
  }

  async start() {
    if (this.listening) return;
    if (!this.supported) {
      this.hooks.onError?.("voice input needs Chrome or Edge");
      return;
    }
    try {
      await this.audio.micStart(); // the line waves with your voice
    } catch {
      this.hooks.onError?.("microphone permission denied");
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    rec.interimResults = true;
    rec.continuous = false;
    rec.lang = navigator.language || "en-US"; // speak any language :  answers stay English
    this._final = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) this._final += t;
        else interim += t;
      }
      this.hooks.onInterim?.((this._final + interim).trim());
    };
    rec.onerror = (e) => {
      this._err = e.error;
      if (e.error === "no-speech")
        this.hooks.onError?.("didn't hear anything, try again");
      else if (e.error === "network")
        this.hooks.onError?.("speech service unreachable; Chrome speech needs internet");
      else if (e.error === "not-allowed" || e.error === "service-not-allowed")
        this.hooks.onError?.("microphone blocked; allow it in the address bar");
      else if (e.error !== "aborted")
        this.hooks.onError?.("voice: " + e.error);
    };
    rec.onend = () => this._finish();
    this._rec = rec;
    this._err = null;
    this._t0 = performance.now();
    this._retries = 0;
    this.listening = true;
    this.drawIcon();
    this.hooks.onStateChange?.(true);
    rec.start();
  }

  // stop listening and send whatever was heard
  stop() {
    if (this._rec) this._rec.stop(); // triggers onend -> _finish
  }

  // stop listening and throw the transcript away
  cancel() {
    this._final = "";
    if (this._rec) {
      this._rec.onend = () => this._finish(true);
      this._rec.abort();
    } else {
      this._finish(true);
    }
  }

  _finish(discard = false) {
    if (!this.listening) return;
    // Chrome sometimes ends a fresh recognition instantly with no error and
    // no words :  restart quietly instead of closing the mic on the user
    if (!discard && !this._final.trim() && !this._err && this._rec &&
        performance.now() - this._t0 < 2000 && this._retries < 2) {
      this._retries += 1;
      try { this._rec.start(); return; } catch { /* fall through to close */ }
    }
    this.listening = false;
    this._rec = null;
    this.audio.micStop();
    this.drawIcon();
    this.hooks.onStateChange?.(false);
    const text = this._final.trim();
    this._final = "";
    if (!discard && text) this.hooks.onFinal?.(text);
    else this.hooks.onInterim?.("");
  }
}
