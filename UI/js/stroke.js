// A single drawable stroke: polyline rendered as ribbon (core + halo),
// with draw-on progress, opacity, morphing, and emphasis pulse.
import * as THREE from "three";
import { resample, clamp01 } from "./geom.js";

const CORE_W = 0.0032;
const HALO_W = 0.013;
// opts.width scales both: small UI text passes < 1 so the glow halo doesn't
// swallow the letterforms (a fixed halo is ~half the cap height at size .05)

export class Stroke {
  constructor(scene3, pts, opts = {}) {
    this.n = Math.max(8, opts.points || Math.min(400, Math.max(32, pts.length * 2)));
    this.pts = resample(pts, this.n);
    this.from = null; // morph source
    this.morphP = 1;
    this.progress = 0; // draw-on 0..1
    this.opacity = 1;
    this.pulse = 0; // emphasis
    this.dead = false;

    const wf = opts.width ?? 1;
    this._coreW = CORE_W * wf;
    this._haloW = HALO_W * wf;
    this.core = this._mesh(1.0, THREE.NormalBlending, opts.color ?? 0xffffff);
    this.halo = this._mesh(0.12, THREE.AdditiveBlending, opts.color ?? 0xffffff);
    scene3.add(this.halo);
    scene3.add(this.core);
    this._scene3 = scene3;
    this._sync();
  }

  _mesh(baseOpacity, blending, color) {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute(
      "position",
      new THREE.BufferAttribute(new Float32Array(this.n * 2 * 3), 3).setUsage(THREE.DynamicDrawUsage)
    );
    const idx = [];
    for (let i = 0; i < this.n - 1; i++) {
      const a = 2 * i, b = 2 * i + 1, c = 2 * i + 2, d = 2 * i + 3;
      idx.push(a, b, c, b, d, c);
    }
    geo.setIndex(idx);
    const mat = new THREE.MeshBasicMaterial({
      color, transparent: true, opacity: baseOpacity, blending,
      depthTest: false, depthWrite: false,
    });
    mat.userData.base = baseOpacity;
    const mesh = new THREE.Mesh(geo, mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = 1;
    return mesh;
  }

  morphTo(pts) {
    this.from = this.pts.map((p, i) => this._current(i)); // from wherever it is now
    this.pts = resample(pts, this.n);
    this.morphP = 0;
  }

  update(dt) {
    if (this.morphP < 1) this.morphP = clamp01(this.morphP + dt / 0.9);
    if (this.pulse > 0) this.pulse = Math.max(0, this.pulse - dt / 0.9);
    this._sync();
  }

  _current(i) {
    if (this.morphP >= 1 || !this.from) return this.pts[i];
    const p = this.morphP < 0.5 ? 2 * this.morphP * this.morphP : 1 - Math.pow(-2 * this.morphP + 2, 2) / 2;
    return [
      this.from[i][0] + (this.pts[i][0] - this.from[i][0]) * p,
      this.from[i][1] + (this.pts[i][1] - this.from[i][1]) * p,
    ];
  }

  _sync() {
    const visible = Math.max(1, Math.floor(this.progress * (this.n - 1)));
    for (const [mesh, hw0] of [[this.core, this._coreW], [this.halo, this._haloW]]) {
      const hw = hw0 * (1 + this.pulse * 1.6);
      const pos = mesh.geometry.attributes.position.array;
      for (let i = 0; i < this.n; i++) {
        const [x, y] = this._current(i);
        const [xp, yp] = this._current(i === 0 ? 0 : i - 1);
        const [xn, yn] = this._current(i === this.n - 1 ? this.n - 1 : i + 1);
        let tx = xn - xp, ty = yn - yp;
        const len = Math.hypot(tx, ty) || 1;
        const nx = (-ty / len) * hw, ny = (tx / len) * hw;
        const o = i * 6;
        pos[o] = x + nx; pos[o + 1] = y + ny; pos[o + 2] = 0;
        pos[o + 3] = x - nx; pos[o + 4] = y - ny; pos[o + 5] = 0;
      }
      mesh.geometry.attributes.position.needsUpdate = true;
      mesh.geometry.setDrawRange(0, visible * 6);
      mesh.material.opacity = mesh.material.userData.base * this.opacity * (mesh === this.halo ? 1 + this.pulse * 2.2 : 1);
      mesh.visible = this.opacity > 0.005;
    }
  }

  dispose() {
    this._scene3.remove(this.core);
    this._scene3.remove(this.halo);
    this.core.geometry.dispose();
    this.halo.geometry.dispose();
    this.core.material.dispose();
    this.halo.material.dispose();
    this.dead = true;
  }
}
