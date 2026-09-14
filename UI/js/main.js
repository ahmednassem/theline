// The Line :  state machine, animation loop, and the segment director.
// States: idle (breathing), thinking (ripple), speaking (voice-driven wave).
// Presenting: whenever something is on stage the line fades away in place,
// and fades back in when the stage is empty again.
import { LineRenderer, N } from "./line.js";
import { AudioReactor } from "./audio.js";
import { fnoise, snoise } from "./noise.js";
import { StrokeScene } from "./scene.js";
import { Director, setVoiceId, getVoiceId } from "./director.js";
import { loadFont, textStrokes } from "./hershey.js";
import { Settings } from "./settings.js";
import { Mic } from "./mic.js";
import { apiHeaders, hasLocalLlmKey } from "./api.js";

const canvas = document.getElementById("cv");
const hint = document.getElementById("hint");
const askBox = document.getElementById("ask");

// ?capture :  clean stage for video recording: no icons, no hint, no input
const CAPTURE = new URLSearchParams(location.search).has("capture");
if (CAPTURE) {
  hint.style.display = "none";
  askBox.style.display = "none";
}
const line = new LineRenderer(canvas);
const audio = new AudioReactor();
const scene = new StrokeScene(line.scene); // the answer stage
const ui = new StrokeScene(line.scene); // gear + settings, also pure strokes

// ---------------------------------------------------------------- state
const MODES = ["idle", "thinking", "speaking"];
let active = "idle";
let split = 0; // 0 = one white line, 1 = split into colored sub-waves
let hide = 0; // 1 = line hidden (something is on stage)
const weights = { idle: 1, thinking: 0, speaking: 0 };

function setMode(m) {
  active = m;
  if (m !== "speaking") audio.stop();
}

const director = new Director(scene, audio, {
  onState: (m) => {
    setMode(m);
    // pseudo envelope only when real narration audio isn't playing
    audio.setPseudo(m === "speaking" && !audio.playing);
  },
  onDone: () => {
    window.__lineDone = true; // offline video-capture tool watches this
    setAskHidden(false);
  },
});

// demo explanation :  same segment format the server will stream in M3
const DEMO = [
  {
    narration: "Let's look at the sine wave, one of the most fundamental shapes in mathematics.",
    ops: [{ op: "axes", x: [0, 6.28], y: [-1.4, 1.4] }],
  },
  {
    narration: "As an angle grows, its sine rises and falls, tracing this smooth, endlessly repeating curve.",
    ops: [
      { op: "plot", fn: "sin(x)", domain: [0, 6.28], id: "sine" },
      { op: "write", text: "y = sin(x)", at: [0.62, 0.56], size: 0.085, id: "label" },
    ],
  },
  {
    narration: "And one full turn of a circle completes exactly one cycle of the wave.",
    ops: [
      { op: "circle", at: [7.2, 0], r: 0.15, id: "circ" },
      { op: "emphasize", id: "sine" },
    ],
  },
];

// simple explanation :  no big drawing, so the line stays (docked) while
// the answer appears above it
const SIMPLE = [
  {
    narration: "Twelve times twelve? That one's easy.",
    ops: [],
  },
  {
    narration: "Twelve squared is one hundred and forty four.",
    ops: [{ op: "write", text: "12 x 12 = 144", at: [0, 0.25], size: 0.14, id: "ans" }],
  },
];

let fontOk = false;
loadFont().then(() => (fontOk = true));

// ---------------------------------------------------------------- session
// one continuous conversation: every question carries the full history
const history = [];
function newChat() {
  history.length = 0;
  // back to the home stage: settings closed, nothing playing, input ready
  settings.close();
  hideDemoMenu();
  director.stop();
  audio.stop();
  setMode("idle");
  setAskHidden(false);
  askBox.value = "";
  askBox.placeholder = "ask anything";
    showHint("new chat: ask anything");
}

// ---------------------------------------------------------------- settings
const getDepth = () => localStorage.getItem("line-depth") || "auto";
const getMode = () => localStorage.getItem("line-mode") || "auto";

// when settings owns the ask box, Enter saves a config field instead of asking
let editingField = null;
function closeEditBox() {
  editingField = null;
  askBox.placeholder = "ask anything";
  askBox.value = "";
  askBox.classList.remove("open", "edit");
  askBox.blur();
  settings.dimPanel(false); // bring the panel back
}

// the input NEVER hides :  always on stage, always ready
function setAskHidden(h) {
  if (h) askBox.blur(); // just drop keyboard focus when a show starts
}

const settings = new Settings(line, ui, audio, {
  getVoiceId,
  setVoiceId,
  getDepth,
  setDepth: (d) => localStorage.setItem("line-depth", d),
  getMode,
  setMode: (m) => localStorage.setItem("line-mode", m),
  newChat,
  hint: (msg, ms) => showHint(msg, ms),
  canOpen: () => fontOk,
  editField: (field, label) => {
    editingField = field;
    settings.dimPanel(true); // panel steps back while typing
    askBox.placeholder = `type new ${label}, enter to save, esc to cancel`;
    askBox.value = "";
    askBox.classList.remove("hidden");
    askBox.classList.add("open", "edit");
    askBox.focus();
  },
  onOpenChange: (open) => {
    // the input leaves the stage while the settings panel is up
    askBox.classList.toggle("hidden", open);
    // the list icon hides so "new chat" has the bottom row to itself
    setUiOpacity("demo-icon", open ? 0 : 0.35);
    if (open) {
      director.pauseHold(); // the show waits; it continues on close
      hideDemoMenu();
      setMode("thinking");
    } else {
      if (editingField) closeEditBox();
      setMode("idle");
      director.resumeHold(); // back to the show, from the current scene
    }
  },
});
if (!CAPTURE) settings.drawGear();

// ---------------------------------------------------------------- voice in
const mic = new Mic(line, ui, audio, {
  onStateChange: (on) => {
    if (on) {
      director.stop();
      setMode("speaking"); // the line waves along with YOUR voice
      setAskHidden(false);
      askBox.classList.add("open");
      askBox.placeholder = "listening...";
    } else {
      setMode("idle");
      askBox.placeholder = "ask anything";
      if (!askBox.value) askBox.classList.remove("open");
    }
  },
  onInterim: (text) => { askBox.value = text; },
  onFinal: (text) => {
    askBox.value = "";
    askBox.classList.remove("open");
    ask(text);
  },
  onError: (msg) => showHint(msg),
});
if (!CAPTURE) mic.drawIcon();

// available narration voices (from the server's verified list)
let voices = [{ name: "Brian", id: "nPczCjzI2devNBz1zQrb" }];
fetch("api/voices").then((r) => {
  if (!r.ok) throw new Error("no api");
  return r.json();
}).then((v) => {
  if (Array.isArray(v) && v.length) {
    voices = v;
    settings.setVoices(v);
  }
}).catch(() => {});
settings.setVoices(voices);

// can this page ask live questions? server-side keys (localhost) or the
// visitor's own keys from settings (hosted, sent per request)
let serverOk = false;
let llmConfigured = false;
fetch("api/health").then((r) => (r.ok ? r.json() : null)).then((h) => {
  if (h && h.server) {
    serverOk = true;
    llmConfigured = !!h.llm_configured;
  }
}).catch(() => {});

// ---------------------------------------------------------------- demos
// recorded answers (real pipeline output, pi with real narration embedded)
// live behind a small stroke-drawn list icon at the bottom
let demoIndex = []; // [{slug, question}]
let demoItems = []; // clickable question rects
let demoMenuOpen = false;
let demoIconRect = null;

fetch("demos/index.json").then((r) => (r.ok ? r.json() : [])).then((idx) => {
  if (!Array.isArray(idx) || !idx.length) return;
  demoIndex = idx;
  drawDemoIcon();
  // hosted with no keys yet: point at the two ways to get something playing
  setTimeout(() => {
    if (serverOk && !llmConfigured && !hasLocalLlmKey()) {
      showHint("pick a recorded demo (list icon), or add your own api key in settings for live answers", 9000);
    } else if (!serverOk) {
      showHint("cached demos only (list icon): run The Line locally for live answers", 8000);
    }
  }, 1500);
}).catch(() => {});

function setUiOpacity(id, o) {
  const g = ui.strokes.get(id);
  if (g) g.forEach((s) => { if (!s.dead) s.opacity = o; });
}

// small list glyph: three bulleted lines
function demoIconPolys(cx, cy) {
  const polys = [];
  for (let k = 0; k < 3; k++) {
    const y = cy + (1 - k) * 0.032;
    const dot = [];
    for (let i = 0; i <= 8; i++) {
      const a = (i / 8) * 2 * Math.PI;
      dot.push([cx - 0.045 + 0.007 * Math.cos(a), y + 0.007 * Math.sin(a)]);
    }
    polys.push(dot);
    polys.push([[cx - 0.026, y], [cx + 0.05, y]]);
  }
  return polys;
}

function drawDemoIcon() {
  if (!demoIndex.length || CAPTURE) return;
  const cx = -line.aspect + 0.3, cy = -0.82;
  ui.draw("demo-icon", demoIconPolys(cx, cy), { color: 0xffffff });
  setUiOpacity("demo-icon", demoMenuOpen ? 0.7 : 0.35);
  const pad = 0.06;
  demoIconRect = { x0: cx - pad, x1: cx + pad, y0: cy - pad, y1: cy + pad };
}
window.addEventListener("resize", () => setTimeout(drawDemoIcon, 60));

function toggleDemoMenu() {
  if (demoMenuOpen) {
    hideDemoMenu();
    director.resumeHold(); // closing the list continues the show
    return;
  }
  // opening the list mid-demo holds the show (it continues on close)
  director.pauseHold();
  setMode("idle");
  setAskHidden(false);
  drawDemoMenu();
}

function drawDemoMenu() {
  if (!fontOk || !demoIndex.length || settings.open) return;
  demoMenuOpen = true;
  askBox.classList.add("hidden"); // input steps out while the list is up
  demoItems = [];
  const { strokes: ts } = textStrokes("- recorded demos -", 0, 0.72, 0.045, "center");
  ui.draw("demo-title", ts, { color: 0xb9c2cc, width: 0.55 });
  setUiOpacity("demo-title", 0.5);
  const maxW = line.aspect * 2 * 0.92; // fit narrow screens
  demoIndex.forEach((d, i) => {
    const y = 0.6 - i * 0.1; // stays fully above the resting line
    let size = 0.06;
    const probe = textStrokes(d.question, 0, 0, size, "center").width;
    if (probe > maxW) size *= maxW / probe;
    const { strokes, width } = textStrokes(d.question, 0, y, size, "center");
    const id = "demo-q-" + d.slug;
    ui.draw(id, strokes, { color: 0xffffff, width: 0.72 });
    setUiOpacity(id, 0.7);
    demoItems.push({ id, slug: d.slug, rect: { x0: -width / 2 - 0.06, x1: width / 2 + 0.06, y0: y - 0.05, y1: y + 0.08 } });
  });
  setUiOpacity("demo-icon", 0.7);
}

function hideDemoMenu() {
  if (!demoMenuOpen && !demoItems.length) return;
  demoMenuOpen = false;
  if (!settings.open) askBox.classList.remove("hidden");
  ui.fade("demo-title", 0.3);
  for (const it of demoItems) ui.fade(it.id, 0.3);
  demoItems = [];
  setUiOpacity("demo-icon", 0.35);
}

async function playDemo(slug) {
  clearStageNote();
  hideDemoMenu();
  director.stop();
  setMode("thinking");
  window.__lineDone = false;
  window.__audioLog = [];
  try {
    const d = await fetch(`demos/${slug}.json`).then((r) => r.json());
    director.play(d.segments); // play() stops first, which would unhide
    setAskHidden(true);
  } catch {
    setMode("idle");
    setAskHidden(false);
    showHint("couldn't load that demo");
  }
}
window.__line = { playDemo }; // hook for the offline video-capture tool

function matchDemo(question) {
  const toks = (s) => new Set(s.toLowerCase().match(/[a-z0-9]+/g) || []);
  const q = toks(question);
  let best = null, bestScore = 0;
  for (const d of demoIndex) {
    let score = 0;
    for (const w of toks(d.question)) if (q.has(w) && w.length > 2) score++;
    if (q.has("pi") && d.slug === "pi") score += 2;
    if (score > bestScore) { best = d; bestScore = score; }
  }
  return bestScore > 0 ? best : null;
}

// mouse -> world coords for stroke hit-testing
function worldXY(e) {
  return [
    ((e.clientX / window.innerWidth) * 2 - 1) * line.aspect,
    -((e.clientY / window.innerHeight) * 2 - 1),
  ];
}
function inRect(r, x, y) {
  return r && x >= r.x0 && x <= r.x1 && y >= r.y0 && y <= r.y1;
}
window.addEventListener("click", (e) => {
  if (e.target === askBox) return; // clicking the input just focuses it
  const [x, y] = worldXY(e);
  if (settings.click(x, y)) return;
  if (mic.click(x, y)) return;
  if (inRect(demoIconRect, x, y)) { toggleDemoMenu(); return; }
  for (const it of demoItems) {
    if (inRect(it.rect, x, y)) { playDemo(it.slug); return; }
  }
});
window.addEventListener("mousemove", (e) => {
  const [x, y] = worldXY(e);
  const overIcon = inRect(demoIconRect, x, y);
  if (!settings.open) setUiOpacity("demo-icon", overIcon || demoMenuOpen ? 0.7 : 0.35);
  let overItem = false;
  for (const it of demoItems) {
    const on = inRect(it.rect, x, y);
    if (on) overItem = true;
    setUiOpacity(it.id, on ? 1 : 0.7);
  }
  const over = settings.move(x, y) || mic.move(x, y) || overIcon || overItem;
  canvas.style.cursor = over ? "pointer" : "default";
});

function showHint(msg, ms = 2400) {
  hint.textContent = msg;
  hint.style.opacity = "1";
  clearTimeout(showHint._t);
  showHint._t = setTimeout(() => (hint.style.opacity = "0"), ms);
}

// ---------------------------------------------------------------- ask
// Enter opens the input; Enter again sends the question to Claude, which
// streams back segments :  segment 1 starts performing while segment 2 is
// still being generated.
function clearStageNote() {
  ui.fade("stage-note-0", 0.4);
  ui.fade("stage-note-1", 0.4);
}

// a big stroke-written note on the stage itself :  impossible to miss
function stageNote(lines, color = 0xe07a7a) {
  const maxW = line.aspect * 2 * 0.9;
  lines.forEach((t, i) => {
    let size = 0.08 - i * 0.015;
    const probe = textStrokes(t, 0, 0, size, "center").width;
    if (probe > maxW) size *= maxW / probe;
    const y = 0.45 - i * 0.16;
    const { strokes } = textStrokes(t, 0, y, size, "center");
    ui.draw("stage-note-" + i, strokes, { color, width: 0.85 });
    setTimeout(() => ui.fade("stage-note-" + i, 0.8), 6000);
  });
}

async function ask(question, forcedMode = null) {
  const live = serverOk && (llmConfigured || hasLocalLlmKey());
  if (!live) {
    // no brain available :  play the closest recorded answer instead
    const m = matchDemo(question);
    if (m) {
      showHint("no api key set: playing the closest recorded demo", 6000);
      playDemo(m.slug);
      return;
    }
    if (serverOk) {
      stageNote(["no api key set", "add yours in settings - the gear icon"]);
        showHint("no api key yet: add yours in settings (gear), or pick a recorded demo (list icon)", 7000);
    } else if (demoIndex.length) {
      stageNote(["server offline - recorded demos only", "pick one from the list icon"], 0xb9c2cc);
        showHint("cached demos only (list icon): run The Line locally to ask anything", 6000);
      } else showHint("couldn't reach the brain; is the server running?");
    return;
  }
  clearStageNote();
  settings.close();
  hideDemoMenu();
  director.stop();
  setMode("thinking");
  setAskHidden(true);
  // forced (Ctrl+Enter / "/video") wins; otherwise the mode setting decides
  const pref = getMode(); // auto | video | question
  const mode = forcedMode || (pref === "question" ? "quick" : pref);
    if (mode === "video") showHint("making a video: planning scenes...", 6000);
  history.push({ role: "user", content: question });
  const answerLines = [];
  try {
    const resp = await fetch("api/ask", {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        messages: history, mode, depth: getDepth(),
        aspect: window.innerWidth / window.innerHeight, // real visible width is +-aspect
      }),
    });
    if (!resp.ok || !resp.body) throw new Error("ask " + resp.status);
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const chunk = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!chunk) continue;
        try {
          director.enqueue(JSON.parse(chunk));
          answerLines.push(chunk);
        } catch { /* skip malformed line */ }
      }
    }
    director.end();
    if (answerLines.length) {
      // remember the answer so follow-up questions have context
      history.push({ role: "assistant", content: answerLines.join("\n") });
    } else {
      history.pop();
      setMode("idle");
      setAskHidden(false);
      showHint("no answer, try again");
    }
  } catch (err) {
    history.pop();
    setMode("idle");
    setAskHidden(false);
      showHint("couldn't reach the brain; is the server running?");
  }
}

// one stopper for Esc and Space: closes whatever is on top, then playback
function stopAll() {
  if (mic.listening) { mic.cancel(); return; }
  if (settings.open) { settings.close(); return; } // close() resumes the show
  if (demoMenuOpen) { hideDemoMenu(); director.resumeHold(); return; }
  director.stop();
  audio.stop();
  setAskHidden(false);
}

window.addEventListener("keydown", (e) => {
  const typing = document.activeElement === askBox;
  if (e.key === "Enter") {
    if (typing && editingField) {
      const v = askBox.value.trim();
      if (v) {
        settings.saveField(editingField, v);
        showHint("saved");
      }
      closeEditBox();
      return;
    }
    if (!typing) {
      askBox.classList.add("open");
      askBox.focus();
    } else if (askBox.value.trim()) {
      let q = askBox.value.trim();
      // Ctrl+Enter or a "/video " prefix forces a full multi-scene video
      let forced = e.ctrlKey ? "video" : null;
      if (/^\/video\s+/i.test(q)) {
        forced = "video";
        q = q.replace(/^\/video\s+/i, "");
      }
      askBox.value = "";
      askBox.classList.remove("open");
      askBox.blur();
      ask(q, forced);
    }
    return;
  }
  if (e.key === "Escape") {
    if (typing) { closeEditBox(); return; }
    stopAll();
    return;
  }
  if (typing) return; // let the user type freely
  if (e.key === " ") { e.preventDefault(); stopAll(); return; } // space = stop
  // just start typing anywhere :  the keystroke lands in the input, no
  // Enter or click needed first
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    askBox.classList.add("open");
    askBox.focus();
    return; // the default action types this key into the now-focused input
  }
  if (settings.open) return; // stage belongs to settings
  if (e.key === "1") { director.stop(); setMode("idle"); }
  if (e.key === "2") { director.stop(); setMode("thinking"); }
  if (e.key === "3") {
    director.stop();
    setMode("speaking");
    audio.playTest("audio/test.wav");
  }
  if ((e.key === "d" || e.key === "D") && fontOk) {
    director.stop();
    setMode("thinking");
    setTimeout(() => director.play(DEMO), 900);
  }
  if ((e.key === "s" || e.key === "S") && fontOk) {
    director.stop();
    setMode("thinking");
    setTimeout(() => director.play(SIMPLE), 700);
  }
  if (e.key === "v" || e.key === "V") {
    const i = voices.findIndex((v) => v.id === getVoiceId());
    const nv = voices[(i + 1) % voices.length];
    setVoiceId(nv.id);
    showHint("voice: " + nv.name);
  }
});

// ---------------------------------------------------------------- motion
const taper = new Float32Array(N);
for (let i = 0; i < N; i++) {
  const u = (i / (N - 1)) * 2 - 1;
  taper[i] = Math.pow(Math.cos((u * Math.PI) / 2), 0.65);
}

function yIdle(u, t) {
  // irregular breathing: sine + slow noise so it never loops perfectly
  const breath = 0.55 + 0.45 * (0.6 * Math.sin(t * 0.5) + 0.4 * snoise(0.3, t * 0.13));
  return (
    breath *
      (0.02 * Math.sin(u * 3.1 + t * 0.45) +
        0.013 * Math.sin(u * 6.7 - t * 0.3) ) +
    0.011 * fnoise(u * 1.4 + t * 0.05, t * 0.1, 2)
  );
}

function yThinking(u, t) {
  // clean, regular traveling wave :  calm and steady, nothing fighting
  return (
    0.036 * Math.sin(u * 6.0 - t * 2.2) +
    0.012 * Math.sin(u * 12.0 - t * 4.4)
  );
}

function ySpeaking(u, t, level) {
  const win = Math.exp(-u * u * (2.0 - 0.6 * level)); // widens when louder
  const busy = 1 + level * 0.35; // louder = slightly busier, stays smooth
  const wave =
    0.18 * Math.sin(u * 8.0 * busy + t * 2.0) +
    0.09 * Math.sin(u * 13.0 * busy - t * 3.2) +
    0.03 * fnoise(u * 3.0, t * 0.8, 1);
  const residual = 0.006 * Math.sin(u * 3.0 + t * 0.8);
  return level * win * wave + residual;
}

// Siri-style colored sub-waves
function ySub(u, t, level, k) {
  const ph = k * 2.3;
  const fm = 1 + 0.22 * (k - 1);
  const win = Math.exp(-u * u * (2.2 - 0.5 * level));
  const wave =
    0.15 * Math.sin(u * 7.4 * fm + t * (2.2 + 0.4 * k) + ph) +
    0.08 * Math.sin(u * 12.0 * fm - t * (2.9 + 0.5 * k) + ph * 1.7) +
    0.025 * fnoise(u * 2.8 + k * 9.1, t * 0.9, 1);
  return level * win * wave;
}

// ---------------------------------------------------------------- loop
let last = performance.now();

function frame(now) {
  const dt = Math.min(0.05, (now - last) / 1000);
  last = now;
  const t = now / 1000;

  for (const m of MODES) {
    const target = m === active ? 1 : 0;
    const k = 1 - Math.exp(-dt / 0.3);
    weights[m] += (target - weights[m]) * k;
  }

  const level = audio.update(dt);

  const splitTarget = active === "speaking" ? 1 : 0;
  split += (splitTarget - split) * (1 - Math.exp(-dt / 0.45));

  // anything on stage (answer or settings) -> the line fades away in place
  const strokesOn = scene.strokes.size > 0 || scene.busy || settings.open;
  hide += ((strokesOn ? 1 : 0) - hide) * (1 - Math.exp(-dt / 0.35));
  const vis = 1 - hide;
  line.setOpacity(vis);

  const ys = line.ys;
  for (let i = 0; i < N; i++) {
    const u = (i / (N - 1)) * 2 - 1;
    let y = 0;
    if (weights.idle > 0.001) y += weights.idle * yIdle(u, t);
    if (weights.thinking > 0.001) y += weights.thinking * yThinking(u, t);
    if (weights.speaking > 0.001) y += weights.speaking * ySpeaking(u, t, level);
    ys[i] = y * taper[i];
  }

  const subLevel = level;
  for (let k = 0; k < line.subs.length; k++) {
    const sub = line.subs[k];
    line.setSubGlow(k, split * (0.22 + 0.5 * subLevel) * vis);
    if (!sub.mesh.visible) continue;
    for (let i = 0; i < N; i++) {
      const u = (i / (N - 1)) * 2 - 1;
      const own = ySub(u, t, subLevel, k) * taper[i];
      sub.ys[i] = ys[i] * (1 - split) + own * split;
    }
  }

  scene.update(dt);
  ui.update(dt);
  line.render();
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

hint.textContent = "just type to ask   Ctrl+Enter full video   Space/Esc stop";
setTimeout(() => (hint.style.opacity = "0"), 10000);
