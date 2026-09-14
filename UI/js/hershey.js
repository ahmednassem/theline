// Hershey stroke font: the line literally handwrites text.
// Parses the classic .jhf format (ASCII 32..126). timesr = Times Roman,
// the serif look of a classic 3b1b title card.
let glyphs = null; // char -> { left, right, strokes: [ [[x,y],...], ... ] }

export async function loadFont(url = "lib/timesr.jhf") {
  const raw = await (await fetch(url)).text();
  // glyphs may wrap across lines: a continuation line does not start with
  // 5 digits + 3-digit vertex count that matches remaining data, so instead
  // we accumulate: each glyph declares its vertex count up front.
  const lines = raw.split(/\r?\n/).filter((l) => l.length > 0);
  const records = [];
  let cur = null;
  let need = 0;
  for (const line of lines) {
    if (cur === null) {
      need = parseInt(line.slice(5, 8), 10) * 2 - 2; // chars of coord data after bounds
      cur = line.slice(8);
    } else {
      cur += line;
    }
    if (cur.length >= need + 2) {
      records.push(cur);
      cur = null;
    }
  }

  glyphs = {};
  const R = "R".charCodeAt(0);
  records.forEach((rec, idx) => {
    const ch = String.fromCharCode(32 + idx);
    const left = rec.charCodeAt(0) - R;
    const right = rec.charCodeAt(1) - R;
    const strokes = [];
    let pen = [];
    for (let i = 2; i + 1 < rec.length; i += 2) {
      if (rec[i] === " " && rec[i + 1] === "R") {
        if (pen.length > 1) strokes.push(pen);
        pen = [];
      } else {
        pen.push([rec.charCodeAt(i) - R, rec.charCodeAt(i + 1) - R]);
      }
    }
    if (pen.length > 1) strokes.push(pen);
    glyphs[ch] = { left, right, strokes };
  });
}

export function fontReady() {
  return !!glyphs;
}

// Layout text -> array of polylines in world coords.
// size = capital height in world units. anchor: "left" | "center".
// Returns { strokes, width }.
export function textStrokes(text, x, y, size, anchor = "left") {
  if (!glyphs) throw new Error("font not loaded");
  const s = size / 21; // hershey cap height ~21 units
  // measure
  let width = 0;
  for (const ch of text) {
    const g = glyphs[ch] || glyphs["?"];
    width += (g.right - g.left) * s;
  }
  let cx = anchor === "center" ? x - width / 2 : x;
  const out = [];
  for (const ch of text) {
    const g = glyphs[ch] || glyphs["?"];
    for (const st of g.strokes) {
      out.push(st.map(([gx, gy]) => [cx + (gx - g.left) * s, y - gy * s]));
    }
    cx += (g.right - g.left) * s;
  }
  return { strokes: out, width };
}
