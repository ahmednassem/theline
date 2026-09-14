// The Line renderer: one polyline drawn as a glowing ribbon (core + halo pass).
// THREE.Line linewidth is broken on Windows/ANGLE, so we build quad strips.
import * as THREE from "three";

export const N = 512; // number of points along the line :  fixed forever

export class LineRenderer {
  constructor(canvas) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x000000);
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -10, 10);

    this.xs = new Float32Array(N); // world x per point (set in resize)
    this.ys = new Float32Array(N); // world y per point (set by animator)

    this.core = this._makeRibbon(1.0, THREE.NormalBlending);
    this.halo = this._makeRibbon(0.16, THREE.AdditiveBlending);

    // Siri-style sub-lines: thin colored waves that separate from the main
    // line while speaking and collapse back into it when quiet.
    this.subColors = [0x38c8ff, 0xff4fa3, 0x63ff9e];
    this.subs = this.subColors.map((c) => {
      const r = this._makeRibbon(0.0, THREE.AdditiveBlending);
      r.mesh.material.color.set(c);
      r.ys = new Float32Array(N);
      this.scene.add(r.mesh);
      return r;
    });

    this.scene.add(this.halo.mesh);
    this.scene.add(this.core.mesh);

    this.coreWidth = 0.0034;
    this.haloWidth = 0.02;
    this.subWidth = 0.0045;

    window.addEventListener("resize", () => this.resize());
    this.resize();
  }

  _makeRibbon(opacity, blending) {
    const geo = new THREE.BufferGeometry();
    const pos = new Float32Array(N * 2 * 3);
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
    const idx = [];
    for (let i = 0; i < N - 1; i++) {
      const a = 2 * i, b = 2 * i + 1, c = 2 * i + 2, d = 2 * i + 3;
      idx.push(a, b, c, b, d, c);
    }
    geo.setIndex(idx);
    const mat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      transparent: opacity < 1,
      opacity,
      blending,
      depthTest: false,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.frustumCulled = false;
    return { geo, pos, mesh };
  }

  resize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.renderer.setSize(w, h);
    this.aspect = w / h;
    this.camera.left = -this.aspect;
    this.camera.right = this.aspect;
    this.camera.updateProjectionMatrix();
    // line spans 88% of the screen width
    const span = this.aspect * 0.88;
    for (let i = 0; i < N; i++) {
      this.xs[i] = -span + (2 * span * i) / (N - 1);
    }
  }

  // Whole-line visibility: 1 = normal, 0 = the line has become the drawing.
  setOpacity(o) {
    this.core.mesh.material.opacity = o;
    this.core.mesh.material.transparent = true;
    this.halo.mesh.material.opacity = 0.16 * o;
    this.core.mesh.visible = o > 0.004;
    this.halo.mesh.visible = o > 0.004;
  }

  // Set visibility/strength of the colored sub-lines (0 = merged & hidden).
  setSubGlow(i, opacity) {
    this.subs[i].mesh.material.opacity = opacity;
    this.subs[i].mesh.visible = opacity > 0.004;
  }

  // Rebuild all ribbons and render.
  render() {
    this._extrude(this.core, this.coreWidth, this.ys);
    this._extrude(this.halo, this.haloWidth, this.ys);
    for (const s of this.subs) {
      if (s.mesh.visible) this._extrude(s, this.subWidth, s.ys);
    }
    this.renderer.render(this.scene, this.camera);
  }

  _extrude(ribbon, halfWidth, ys) {
    const { pos } = ribbon;
    const xs = this.xs;
    for (let i = 0; i < N; i++) {
      const ip = i === 0 ? 0 : i - 1;
      const inx = i === N - 1 ? N - 1 : i + 1;
      let tx = xs[inx] - xs[ip];
      let ty = ys[inx] - ys[ip];
      const len = Math.hypot(tx, ty) || 1;
      // normal = perpendicular to tangent
      const nx = (-ty / len) * halfWidth;
      const ny = (tx / len) * halfWidth;
      const o = i * 6;
      pos[o] = xs[i] + nx;
      pos[o + 1] = ys[i] + ny;
      pos[o + 2] = 0;
      pos[o + 3] = xs[i] - nx;
      pos[o + 4] = ys[i] - ny;
      pos[o + 5] = 0;
    }
    ribbon.geo.attributes.position.needsUpdate = true;
  }
}
