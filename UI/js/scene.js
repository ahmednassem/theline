// StrokeScene: the drawing surface. Holds strokes and their animations
// (draw-on, fade, morph, emphasize) plus the current plot frame mapping.
import { Stroke } from "./stroke.js";
import { pathLength, clamp01 } from "./geom.js";

const DRAW_SPEED = 2.2; // world units per second of pen travel

export class StrokeScene {
  constructor(scene3) {
    this.scene3 = scene3;
    this.strokes = new Map(); // id -> Stroke[]
    this.anims = [];
    this.frame = null; // set by axes op: math coords -> world coords
    this._auto = 0;
    this.hasBig = false; // a full drawing (axes/plot/shape) is on stage
  }

  // math->world using the current frame
  mapX(x) { const f = this.frame; return f.wx0 + ((x - f.x0) / (f.x1 - f.x0)) * (f.wx1 - f.wx0); }
  mapY(y) { const f = this.frame; return f.wy0 + ((y - f.y0) / (f.y1 - f.y0)) * (f.wy1 - f.wy0); }

  // Add a group of polylines under one id, drawn on sequentially.
  // Returns total draw duration (seconds).
  draw(id, polylines, opts = {}) {
    const group = [];
    let totalLen = 0;
    for (const pts of polylines) totalLen += pathLength(pts);
    const totalDur = Math.min(4.5, Math.max(0.35, totalLen / DRAW_SPEED));
    if (opts.big) this.hasBig = true;
    let t0 = 0;
    for (const pts of polylines) {
      const st = new Stroke(this.scene3, pts, opts);
      const dur = totalDur * (pathLength(pts) / (totalLen || 1e-9));
      this.anims.push({ st, kind: "draw", t: -t0, dur: Math.max(0.05, dur) });
      group.push(st);
      t0 += dur;
    }
    this._store(id, group);
    return totalDur;
  }

  _store(id, group) {
    const key = id || `s${this._auto++}`;
    const prev = this.strokes.get(key);
    if (prev) prev.forEach((s) => !s.dead && this.fadeStroke(s, 0.4));
    this.strokes.set(key, group);
    return key;
  }

  fadeStroke(st, dur = 0.6) {
    this.anims.push({ st, kind: "fade", t: 0, dur: Math.max(dur, 0.4) });
  }

  fade(id, dur = 0.6) {
    const g = this.strokes.get(id);
    if (g) g.forEach((s) => !s.dead && this.fadeStroke(s, dur));
  }

  clear(dur = 0.7) {
    for (const g of this.strokes.values()) g.forEach((s) => !s.dead && this.fadeStroke(s, dur));
    this.strokes.clear();
    this.frame = null;
    this.hasBig = false;
  }

  emphasize(id) {
    const g = this.strokes.get(id);
    if (g) g.forEach((s) => { s.pulse = 1; });
  }

  morph(id, polyline) {
    const g = this.strokes.get(id);
    if (g && g.length) {
      g[0].morphTo(polyline);
      for (let i = 1; i < g.length; i++) this.fadeStroke(g[i], 0.4);
    }
  }

  get busy() {
    return this.anims.length > 0;
  }

  update(dt) {
    const keep = [];
    for (const a of this.anims) {
      a.t += dt;
      if (a.t < 0) { keep.push(a); continue; }
      const p = clamp01(a.t / a.dur);
      if (a.kind === "draw") a.st.progress = p;
      else if (a.kind === "fade") a.st.opacity = 1 - p;
      if (p < 1) keep.push(a);
      else if (a.kind === "fade") a.st.dispose();
    }
    this.anims = keep;
    for (const g of this.strokes.values()) g.forEach((s) => !s.dead && s.update(dt));
  }
}
