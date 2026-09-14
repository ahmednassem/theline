// Geometry helpers shared by the scene engine and DSL compiler.

// Total length of a polyline [[x,y], ...]
export function pathLength(pts) {
  let len = 0;
  for (let i = 1; i < pts.length; i++) {
    len += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
  }
  return len;
}

// Resample a polyline to exactly n points, evenly spaced by arc length.
export function resample(pts, n) {
  if (pts.length < 2) {
    const p = pts[0] || [0, 0];
    return Array.from({ length: n }, () => [p[0], p[1]]);
  }
  const total = pathLength(pts) || 1e-9;
  const out = [[pts[0][0], pts[0][1]]];
  let seg = 1;
  let acc = 0;
  for (let k = 1; k < n - 1; k++) {
    const target = (total * k) / (n - 1);
    while (seg < pts.length - 1) {
      const d = Math.hypot(pts[seg][0] - pts[seg - 1][0], pts[seg][1] - pts[seg - 1][1]);
      if (acc + d >= target) break;
      acc += d;
      seg++;
    }
    const d = Math.hypot(pts[seg][0] - pts[seg - 1][0], pts[seg][1] - pts[seg - 1][1]) || 1e-9;
    const f = (target - acc) / d;
    out.push([
      pts[seg - 1][0] + (pts[seg][0] - pts[seg - 1][0]) * f,
      pts[seg - 1][1] + (pts[seg][1] - pts[seg - 1][1]) * f,
    ]);
  }
  out.push([pts[pts.length - 1][0], pts[pts.length - 1][1]]);
  return out;
}

export const easeInOut = (p) => (p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2);
export const easeOut = (p) => 1 - Math.pow(1 - p, 3);
export const clamp01 = (p) => Math.max(0, Math.min(1, p));
