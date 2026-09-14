// Audio reactor: plays audio through an AnalyserNode and exposes smoothed loudness.
export class AudioReactor {
  constructor() {
    this.ctx = null;
    this.analyser = null;
    this.el = null;
    this.buf = null;
    this.level = 0; // smoothed 0..1
    this.pseudo = false; // synthetic voice envelope (browser TTS has no analyser)
    this._pt = 0;
  }

  setPseudo(on) {
    this.pseudo = on;
  }

  _ensure() {
    if (this.ctx) return;
    this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 1024;
    this.buf = new Float32Array(this.analyser.fftSize);
    // analyser -> out gain -> speakers; the gain is muted while the mic is
    // live so the user doesn't hear themselves echoed
    this.out = this.ctx.createGain();
    this.analyser.connect(this.out);
    this.out.connect(this.ctx.destination);
  }

  // Play a URL through the analyser (looping test audio for now).
  playTest(url) {
    this._ensure();
    if (this.el) { this.el.pause(); this.el = null; }
    this.el = new Audio(url);
    this.el.loop = true;
    this.el.crossOrigin = "anonymous";
    const src = this.ctx.createMediaElementSource(this.el);
    src.connect(this.analyser);
    this.ctx.resume();
    this.el.play();
  }

  // Play narration audio bytes (mp3) through the analyser: the wave follows
  // the REAL voice loudness. Returns { duration, ended: Promise }.
  async playNarration(arrayBuffer) {
    this._ensure();
    await this.ctx.resume();
    const buf = await new Promise((res, rej) => this.ctx.decodeAudioData(arrayBuffer, res, rej));
    this.stopNarration();
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    src.connect(this.analyser);
    this._src = src;
    this._srcOn = true;
    const ended = new Promise((res) => (src.onended = () => { this._srcOn = false; res(); }));
    src.start();
    return { duration: buf.duration, ended };
  }

  stopNarration() {
    if (this._src) {
      try { this._src.stop(); } catch { /* already stopped */ }
      this._src = null;
      this._srcOn = false;
    }
  }

  // Route the microphone through the analyser (not to the speakers), so the
  // line waves along with the USER's voice while they talk to it.
  async micStart() {
    this._ensure();
    await this.ctx.resume();
    if (this._micOn) return;
    this._micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this._micSrc = this.ctx.createMediaStreamSource(this._micStream);
    this._micSrc.connect(this.analyser);
    this.out.gain.value = 0; // no echo
    this._micOn = true;
  }

  micStop() {
    if (!this._micOn) return;
    this._micSrc.disconnect();
    this._micStream.getTracks().forEach((t) => t.stop());
    this._micSrc = null;
    this._micStream = null;
    this._micOn = false;
    this.out.gain.value = 1;
  }

  stop() {
    if (this.el) { this.el.pause(); this.el = null; }
    this.stopNarration();
  }

  get playing() {
    return (!!this.el && !this.el.paused) || !!this._srcOn || !!this._micOn;
  }

  // Call once per frame; returns smoothed loudness 0..1 (fast attack, slow release).
  update(dt) {
    let raw = 0;
    if (this.analyser && this.playing) {
      this.analyser.getFloatTimeDomainData(this.buf);
      let sum = 0;
      for (let i = 0; i < this.buf.length; i++) sum += this.buf[i] * this.buf[i];
      raw = Math.min(1, Math.sqrt(sum / this.buf.length) * 4.5);
    } else if (this.pseudo) {
      // speech-like synthetic envelope: syllable bursts with pauses
      this._pt += dt;
      const p = this._pt;
      const gate = Math.sin(p * 1.05) + Math.sin(p * 0.47 + 1.3) > -0.35 ? 1 : 0;
      raw = gate * Math.max(0, 0.5 + 0.3 * Math.sin(p * 7.3) + 0.25 * Math.sin(p * 12.9 + 1.1));
      raw = Math.min(1, raw);
    }
    const tau = raw > this.level ? 0.07 : 0.24; // attack / release seconds (smooth)
    const k = 1 - Math.exp(-dt / tau);
    this.level += (raw - this.level) * k;
    return this.level;
  }
}
