// DSL compiler: visual ops -> stroke drawings on the scene.
// Ops are pure data (later streamed from the server / Claude). Every op is
// guaranteed compilable :  the AI never sends executable code.
//
// Design-space coordinates: x in [-1.4, 1.4], y in [-0.55, 0.9]
// (the docked waveform lives below y ~ -0.65).
import { compileExpr } from "./mathexpr.js";
import { textStrokes } from "./hershey.js";

const AREA = { x0: -1.15, x1: 1.15, y0: -0.42, y1: 0.72 };

// 3blue1brown-style palette; ops may override with color: "name"
const COLORS = {
  white: 0xffffff, grey: 0xb9c2cc,
  blue: 0x58c4dd, yellow: 0xf5d76b, green: 0x83c167,
  red: 0xfc6255, purple: 0xc792ea, teal: 0x5cd0b3,
};
function colorOf(op, fallback) {
  if (typeof op.color === "number") return op.color;
  return COLORS[op.color] ?? COLORS[fallback];
}

// circle/arrow/line positions are PLOT coordinates when axes exist (so the
// AI can mark points on curves), plain screen coordinates otherwise
function pos(scene, p) {
  if (!p) return [0, 0];
  return scene.frame ? [scene.mapX(p[0]), scene.mapY(p[1])] : [p[0], p[1]];
}

function circlePts(cx, cy, r, n = 96) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return pts;
}

function arrowPolys(x0, y0, x1, y1, head = 0.045) {
  const a = Math.atan2(y1 - y0, x1 - x0);
  const h1 = [x1 - head * Math.cos(a - 0.45), y1 - head * Math.sin(a - 0.45)];
  const h2 = [x1 - head * Math.cos(a + 0.45), y1 - head * Math.sin(a + 0.45)];
  return [
    [[x0, y0], [x1, y1]],
    [h1, [x1, y1], h2],
  ];
}

// Execute one op on the scene. Returns duration in seconds of its animation.
export function runOp(scene, op) {
  switch (op.op) {
    case "axes": {
      const [x0, x1] = op.x ?? [-1, 1];
      const [y0, y1] = op.y ?? [-1, 1];
      scene.frame = { x0, x1, y0, y1, wx0: AREA.x0, wx1: AREA.x1, wy0: AREA.y0, wy1: AREA.y1 };
      // axis lines cross at (0,0) if visible, else at edges
      const ax = x0 <= 0 && x1 >= 0 ? scene.mapX(0) : AREA.x0;
      const ay = y0 <= 0 && y1 >= 0 ? scene.mapY(0) : AREA.y0;
      const polys = [
        ...arrowPolys(AREA.x0 - 0.05, ay, AREA.x1 + 0.07, ay),
        ...arrowPolys(ax, AREA.y0 - 0.05, ax, AREA.y1 + 0.07),
      ];
      return scene.draw(op.id || "axes", polys, { color: colorOf(op, "grey"), big: true });
    }

    case "plot": {
      if (!scene.frame) runOp(scene, { op: "axes", x: op.domain, y: op.range ?? [-1.2, 1.2] });
      const fn = compileExpr(op.fn);
      const [d0, d1] = op.domain ?? [scene.frame.x0, scene.frame.x1];
      const pts = [];
      const S = 220;
      for (let i = 0; i <= S; i++) {
        const x = d0 + ((d1 - d0) * i) / S;
        let y = fn(x);
        if (!isFinite(y)) y = 0;
        // clamp into frame so wild functions stay on screen
        y = Math.max(scene.frame.y0, Math.min(scene.frame.y1, y));
        pts.push([scene.mapX(x), scene.mapY(y)]);
      }
      return scene.draw(op.id || `plot-${op.fn}`, [pts], { color: colorOf(op, "blue"), big: true });
    }

    case "write": {
      const size = op.size ?? 0.09;
      const [x, y] = op.at ?? [0, 0.8];
      const { strokes } = textStrokes(String(op.text), x, y, size, op.anchor ?? "center");
      return scene.draw(op.id || `text-${op.text}`, strokes, { color: colorOf(op, "yellow") });
    }

    case "circle": {
      const [cx, cy] = pos(scene, op.at ?? [0, 0.15]);
      return scene.draw(
        op.id || "circle",
        [circlePts(cx, cy, op.r ?? 0.3)], // r stays in screen units
        { color: colorOf(op, "green"), big: true }
      );
    }

    case "arrow": {
      const [fx, fy] = pos(scene, op.from);
      const [tx, ty] = pos(scene, op.to);
      return scene.draw(op.id || "arrow", arrowPolys(fx, fy, tx, ty), {
        color: colorOf(op, "red"),
        big: true,
      });
    }

    case "line": {
      const f = pos(scene, op.from);
      const t = pos(scene, op.to);
      return scene.draw(op.id || "line", [[f, t]], { color: colorOf(op, "white"), big: true });
    }

    case "morph": {
      let target = null;
      if (op.to === "circle") target = circlePts(op.at?.[0] ?? 0, op.at?.[1] ?? 0.15, op.r ?? 0.3);
      else if (op.to === "flat") target = [[-1, 0], [1, 0]];
      if (target) scene.morph(op.id, target);
      return 0.9;
    }

    case "emphasize":
      scene.emphasize(op.id);
      return 0.7;

    case "fade":
      scene.fade(op.id);
      return 0.5;

    case "clear":
      scene.clear();
      return 0.7;

    case "pause":
      return op.seconds ?? 0.8;

    default:
      console.warn("unknown op", op);
      return 0;
  }
}
