// Settings :  drawn entirely with line strokes, like everything else.
// A small stroke-drawn gear sits in the bottom-left; clicking it makes the
// line transition into the settings section: voice names written by the
// line itself. Clicking a name selects it and speaks a short sample.
import { textStrokes } from "./hershey.js";
import {
  activeLlm, apiHeaders, clearLocalKeys, DEFAULT_MODEL,
  getLocal, maskKey, setLocal, setLocalKey,
} from "./api.js";

function gearPolys(cx, cy, r) {
  const polys = [];
  const ring = [];
  for (let i = 0; i <= 40; i++) {
    const a = (i / 40) * 2 * Math.PI;
    ring.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  polys.push(ring);
  for (let k = 0; k < 8; k++) {
    const a = (k / 8) * 2 * Math.PI + Math.PI / 8;
    polys.push([
      [cx + r * 1.08 * Math.cos(a), cy + r * 1.08 * Math.sin(a)],
      [cx + r * 1.55 * Math.cos(a), cy + r * 1.55 * Math.sin(a)],
    ]);
  }
  const hub = [];
  for (let i = 0; i <= 24; i++) {
    const a = (i / 24) * 2 * Math.PI;
    hub.push([cx + r * 0.42 * Math.cos(a), cy + r * 0.42 * Math.sin(a)]);
  }
  polys.push(hub);
  return polys;
}

const DIM = 0.35, LIT = 0.95, ITEM = 0.6;
const SEL_COLOR = 0x58c4dd;

export class Settings {
  constructor(line, ui, audio, hooks) {
    this.line = line;
    this.ui = ui; // its own StrokeScene, separate from the answer stage
    this.audio = audio;
    this.hooks = hooks; // { getVoiceId, setVoiceId, newChat, onOpenChange }
    this.open = false;
    this.tab = "voice"; // voice | brain
    this.config = null; // masked API config (server on localhost, else localStorage)
    this.configSource = "server"; // server | local (bring-your-own-key, hosted)
    this.voices = [];
    this.items = []; // clickable: { id, kind, voice?, rect:{x0,x1,y0,y1} }
    this.gearRect = null;
    this._panelIds = [];
    window.addEventListener("resize", () => setTimeout(() => this.drawGear(), 50));
  }

  async loadConfig() {
    try {
      const r = await fetch("api/config");
      if (!r.ok) throw new Error("config " + r.status);
      this.config = await r.json();
      this.configSource = "server";
    } catch {
      // hosted (or server down): keys live in this browser only and are
      // sent along with each request :  the server never stores them
      this.configSource = "local";
      this.config = this._localConfig();
    }
    if (this.open && this.tab === "brain") this._drawPanel();
  }

  _localConfig() {
    const llm = activeLlm();
    return {
      llm_provider: llm ? llm.provider : "",
      llm_model: llm ? llm.model : getLocal("model") || DEFAULT_MODEL.claude,
      llm_base_url: getLocal("url") || "https://api.openai.com/v1",
      claude_key: maskKey(getLocal("claude")),
      openai_key: maskKey(getLocal("openai")),
      eleven_api_key: maskKey(getLocal("eleven")),
    };
  }

  async saveField(field, value) {
    if (this.configSource === "local") {
      if (field === "claude_api_key") setLocalKey("claude", value);
      else if (field === "openai_api_key") setLocalKey("openai", value);
      else if (field === "eleven_api_key") setLocal("eleven", value);
      else if (field === "llm_model") setLocal("model", value);
      else if (field === "llm_base_url") setLocal("url", value);
      this.config = this._localConfig();
      if (this.open && this.tab === "brain") {
        this._drawPanel();
        this.ui.emphasize("set-edit-" + field);
      }
      return;
    }
    // localhost: the server stores one llm key :  saving a claude or chatgpt
    // key also switches the provider (and the model, if it belongs to the
    // other family)
    const body = {};
    if (field === "claude_api_key" || field === "openai_api_key") {
      const provider = field === "claude_api_key" ? "claude" : "openai";
      body.llm_api_key = value;
      body.llm_provider = provider;
      const model = this.config?.llm_model || "";
      const isClaudeModel = model.startsWith("claude");
      if ((provider === "claude") !== isClaudeModel) body.llm_model = DEFAULT_MODEL[provider];
    } else {
      body[field] = value;
    }
    try {
      const r = await fetch("api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error("config " + r.status);
      this.config = await r.json();
      if (this.open && this.tab === "brain") {
        this._drawPanel();
        this.ui.emphasize("set-edit-" + field);
      }
    } catch { /* refused (not localhost) or server down */ }
  }

  // real, minimal API calls against the entered keys :  result drawn in the
  // panel under the buttons (the bottom hint is invisible behind the panel)
  async checkKeys() {
    this.checkResult = { llm: "checking...", voice: "checking..." };
    if (this.open && this.tab === "brain") this._drawPanel();
    let body = {};
    if (this.configSource === "local") {
      const llm = activeLlm();
      if (llm) {
        body = { llm_api_key: llm.key, llm_provider: llm.provider,
                 llm_model: llm.model, llm_base_url: llm.base_url };
      }
      if (getLocal("eleven")) body.eleven_api_key = getLocal("eleven");
    }
    try {
      const r = await fetch("api/check_keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) throw new Error("check " + r.status);
      const res = await r.json();
      this.checkResult = { llm: res.llm, voice: res.voice };
      const bad = [res.llm, res.voice].filter(
        (s) => s && s !== "no key" && !String(s).startsWith("ok"));
      if (bad.length) this.hooks.hint?.(bad.join("  |  "), 12000);
    } catch {
      this.checkResult = { llm: "server unreachable", voice: "server unreachable" };
      this.hooks.hint?.("check failed: server unreachable", 6000);
    }
    if (this.open && this.tab === "brain") this._drawPanel();
  }

  async clearKeys() {
    if (this.configSource === "local") {
      clearLocalKeys();
      this.config = this._localConfig();
    } else {
      try {
        const r = await fetch("api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clear: ["llm_api_key", "eleven_api_key"] }),
        });
        if (r.ok) this.config = await r.json();
      } catch { /* server down */ }
    }
    this.hooks.hint?.("keys cleared");
    if (this.open && this.tab === "brain") this._drawPanel();
  }

  setVoices(v) {
    this.voices = v;
    if (this.open) this._drawPanel();
  }

  drawGear() {
    const cx = -this.line.aspect + 0.14, cy = -0.82, r = 0.035;
    this.ui.draw("gear", gearPolys(cx, cy, r), { color: 0xffffff });
    this._setOpacity("gear", DIM);
    const pad = 0.055;
    this.gearRect = { x0: cx - pad, x1: cx + pad, y0: cy - pad, y1: cy + pad };
  }

  toggle() {
    this.open ? this.close() : this.openPanel();
  }

  openPanel() {
    if (this.hooks.canOpen && !this.hooks.canOpen()) return;
    this.open = true;
    this.hooks.onOpenChange?.(true);
    this._drawPanel();
    this.loadConfig();
  }

  close() {
    if (!this.open) return;
    this.open = false;
    this.hooks.onOpenChange?.(false);
    for (const id of this._panelIds) this.ui.fade(id, 0.4);
    this._panelIds = [];
    this.items = [];
  }

  _setOpacity(id, o) {
    const g = this.ui.strokes.get(id);
    if (g) g.forEach((s) => { if (!s.dead) s.opacity = o; });
  }

  // while the user types a field value, the panel fades away entirely : 
  // just the input on the black screen, no strokes fighting behind it
  dimPanel(on) {
    if (!this.open) return;
    if (on) {
      for (const id of this._panelIds) this.ui.fade(id, 0.35);
      this._panelIds = [];
      this.items = []; // nothing clickable behind the input
    } else {
      this._drawPanel(); // restore strokes and hit targets
    }
  }

  _write(id, text, x, y, size, color, opacity) {
    const { strokes, width } = textStrokes(text, x, y, size, "center");
    // stroke thickness follows the text size, so small rows stay crisp
    const wf = Math.min(1, Math.max(0.45, size / 0.085));
    this.ui.draw(id, strokes, { color, width: wf });
    this._setOpacity(id, opacity);
    return width;
  }

  // a horizontal row of clickable options; the selected one is highlighted
  _optionRow(kind, options, selected, y, size) {
    const gap = 0.14;
    const widths = options.map((o) => textStrokes(o, 0, 0, size, "center").width);
    const total = widths.reduce((a, b) => a + b, 0) + gap * (options.length - 1);
    let cursor = -total / 2;
    options.forEach((opt, i) => {
      const cx = cursor + widths[i] / 2;
      cursor += widths[i] + gap;
      const id = `set-${kind}-${opt}`;
      const isSel = opt === selected;
      this._write(id, opt, cx, y, size, isSel ? SEL_COLOR : 0xffffff, isSel ? 1 : ITEM);
      this._panelIds.push(id);
      this.items.push({
        id, kind, value: opt,
        rect: { x0: cx - widths[i] / 2 - 0.05, x1: cx + widths[i] / 2 + 0.05, y0: y - size * 0.75, y1: y + size * 0.95 },
      });
    });
  }

  // one "name: value" row that opens the text input when clicked
  _editRow(field, label, value, y, size, color = 0xffffff) {
    const id = "set-edit-" + field;
    const text = `${label}: ${value || "not set"}`;
    // long values shrink to fit narrow screens instead of running off-stage
    const maxW = this.line.aspect * 2 * 0.9;
    const probe = textStrokes(text, 0, 0, size, "center").width;
    if (probe > maxW) size *= maxW / probe;
    const w = this._write(id, text, 0, y, size, color, color === 0xffffff ? ITEM : 0.9);
    this._panelIds.push(id);
    this.items.push({
      id, kind: "edit", field, label,
      rect: { x0: -w / 2 - 0.06, x1: w / 2 + 0.06, y0: y - size * 0.75, y1: y + size * 0.95 },
    });
  }

  _drawPanel() {
    // clear whatever the previous tab drew before redrawing
    for (const id of this._panelIds) this.ui.fade(id, 0.25);
    this.items = [];
    this._panelIds = [];

    this._write("set-title", "settings", 0, 0.74, 0.1, 0xb9c2cc, 0.8);
    this._panelIds.push("set-title");
    this._optionRow("tab", ["voice", "brain"], this.tab, 0.6, 0.065);

    if (this.tab === "voice") this._drawVoiceTab();
    else this._drawBrainTab();

    const ncY = -0.84;
    const w = this._write("set-newchat", "new chat", 0, ncY, 0.07, 0xf5d76b, 0.8);
    this._panelIds.push("set-newchat");
    this.items.push({
      id: "set-newchat", kind: "newchat",
      rect: { x0: -w / 2 - 0.08, x1: w / 2 + 0.08, y0: ncY - 0.07, y1: ncY + 0.09 },
    });
  }

  _drawVoiceTab() {
    const sel = this.hooks.getVoiceId();
    this._write("set-voice-label", "- voice -", 0, 0.46, 0.05, 0xb9c2cc, 0.5);
    this._panelIds.push("set-voice-label");

    const cols = 2, rows = Math.ceil(this.voices.length / cols);
    // columns squeeze in on narrow screens instead of clipping off-stage
    const colOff = Math.min(0.5, Math.max(0.28, this.line.aspect * 0.42));
    const size = 0.062, stepY = 0.088, colX = [-colOff, colOff];
    const topY = 0.36;
    this.voices.forEach((v, i) => {
      const x = colX[Math.floor(i / rows)];
      const y = topY - (i % rows) * stepY;
      const id = "set-v-" + v.id;
      const selected = v.id === sel;
      const w = this._write(id, v.name, x, y, size, selected ? SEL_COLOR : 0xffffff, selected ? 1 : ITEM);
      this._panelIds.push(id);
      this.items.push({
        id, kind: "voice", voice: v,
        rect: { x0: x - w / 2 - 0.06, x1: x + w / 2 + 0.06, y0: y - size * 0.75, y1: y + size * 0.95 },
      });
    });
  }

  _drawBrainTab() {
    this._write("set-depth-label", "- depth -", 0, 0.46, 0.05, 0xb9c2cc, 0.5);
    this._panelIds.push("set-depth-label");
    this._optionRow("depth", ["auto", "surface", "deep", "detailed"], this.hooks.getDepth(), 0.36, 0.062);

    this._write("set-mode-label", "- mode -", 0, 0.24, 0.05, 0xb9c2cc, 0.5);
    this._panelIds.push("set-mode-label");
    this._optionRow("mode", ["auto", "video", "question"], this.hooks.getMode(), 0.14, 0.062);

    this._write("set-api-label", "- api -", 0, 0.0, 0.05, 0xb9c2cc, 0.5);
    this._panelIds.push("set-api-label");
    if (!this.config) {
      this._write("set-api-na", "loading...", 0, -0.12, 0.055, 0xb9c2cc, 0.45);
      this._panelIds.push("set-api-na");
      return;
    }
    const cfg = this.config;
    // no picker: both providers live on the same page :  enter either key,
    // the one set last is what answers (highlighted)
    const active = cfg.llm_provider; // "claude" | "openai" | ""
    const claudeVal = this.configSource === "local"
      ? cfg.claude_key : (active === "claude" ? cfg.llm_api_key : "");
    const openaiVal = this.configSource === "local"
      ? cfg.openai_key : (active === "openai" ? cfg.llm_api_key : "");
    this._editRow("llm_model", "model", cfg.llm_model, -0.1, 0.058);
    if (active === "openai") {
      const url = (cfg.llm_base_url || "").replace(/^https?:\/\//, "");
      this._editRow("llm_base_url", "url", url.length > 30 ? url.slice(0, 30) + "..." : url, -0.22, 0.055);
    }
    this._editRow("claude_api_key", "claude key", claudeVal, -0.34, 0.058,
                  active === "claude" ? SEL_COLOR : 0xffffff);
    this._editRow("openai_api_key", "chatgpt key", openaiVal, -0.46, 0.058,
                  active === "openai" ? SEL_COLOR : 0xffffff);
    this._editRow("eleven_api_key", "voice key", cfg.eleven_api_key, -0.58, 0.058);

    // check both keys with real calls / clear them
    const by = -0.7, bs = 0.055;
    for (const [kind, label, x, color, op] of [
      ["check", "check keys", -0.32, 0xf5d76b, 0.8],
      ["clear", "clear keys", 0.32, 0xffffff, ITEM],
    ]) {
      const id = "set-" + kind;
      const w = this._write(id, label, x, by, bs, color, op);
      this._panelIds.push(id);
      this.items.push({
        id, kind,
        rect: { x0: x - w / 2 - 0.06, x1: x + w / 2 + 0.06, y0: by - bs * 0.75, y1: by + bs * 0.95 },
      });
    }

    // last check verdict, right under the buttons: green ok / red problem
    // (short words so the two columns never collide; detail goes to the hint)
    if (this.checkResult) {
      const col = (s) => String(s).startsWith("ok") ? 0x7ec97e
        : s === "checking..." ? 0xb9c2cc : 0xe07a7a;
      const short = (s) => String(s).startsWith("ok") ? "ok"
        : s === "checking..." ? "..."
        : s === "no key" ? "no key" : "bad";
      this._write("set-checkres-llm", "brain: " + short(this.checkResult.llm),
                  -0.32, -0.79, 0.05, col(this.checkResult.llm), 0.9);
      this._write("set-checkres-voice", "voice: " + short(this.checkResult.voice),
                  0.32, -0.79, 0.05, col(this.checkResult.voice), 0.9);
      this._panelIds.push("set-checkres-llm", "set-checkres-voice");
    }
  }

  _hit(rect, x, y) {
    return rect && x >= rect.x0 && x <= rect.x1 && y >= rect.y0 && y <= rect.y1;
  }

  // returns true if the click was consumed
  click(x, y) {
    if (this._hit(this.gearRect, x, y)) {
      this.toggle();
      return true;
    }
    if (!this.open) return false;
    for (const it of this.items) {
      if (!this._hit(it.rect, x, y)) continue;
      if (it.kind === "voice") this._pickVoice(it.voice);
      else if (it.kind === "depth") {
        this.hooks.setDepth(it.value);
        this._drawPanel();
      } else if (it.kind === "mode") {
        this.hooks.setMode(it.value);
        this._drawPanel();
      } else if (it.kind === "tab") {
        if (this.tab !== it.value) {
          this.tab = it.value;
          this._drawPanel();
        }
      } else if (it.kind === "edit") {
        this.hooks.editField?.(it.field, it.label);
      } else if (it.kind === "check") {
        this.ui.emphasize("set-check");
        this.checkKeys();
      } else if (it.kind === "clear") {
        this.clearKeys();
      } else if (it.kind === "newchat") {
        this.hooks.newChat?.();
        this.ui.emphasize("set-newchat");
      }
      return true;
    }
    return true; // click inside open settings does nothing else
  }

  move(x, y) {
    let cursor = false;
    if (this._hit(this.gearRect, x, y)) cursor = true;
    this._setOpacity("gear", cursor ? LIT : this.open ? 0.7 : DIM);
    if (this.open) {
      const selV = this.hooks.getVoiceId();
      const selD = this.hooks.getDepth();
      const selM = this.hooks.getMode();
      const activeKeyField = this.config?.llm_provider === "claude" ? "claude_api_key"
        : this.config?.llm_provider === "openai" ? "openai_api_key" : null;
      for (const it of this.items) {
        const on = this._hit(it.rect, x, y);
        if (on) cursor = true;
        const isSelected =
          (it.kind === "voice" && it.voice.id === selV) ||
          (it.kind === "depth" && it.value === selD) ||
          (it.kind === "mode" && it.value === selM) ||
          (it.kind === "tab" && it.value === this.tab) ||
          (it.kind === "edit" && it.field === activeKeyField);
        if (["voice", "depth", "mode", "tab", "edit", "clear"].includes(it.kind) && !isSelected)
          this._setOpacity(it.id, on ? LIT : ITEM);
        if (it.kind === "newchat" || it.kind === "check") this._setOpacity(it.id, on ? 1 : 0.8);
      }
    }
    return cursor;
  }

  async _pickVoice(v) {
    if (this.hooks.getVoiceId() !== v.id) {
      this.hooks.setVoiceId(v.id);
      this._drawPanel(); // refresh highlights
    }
    this.ui.emphasize("set-v-" + v.id);
    try {
      const r = await fetch("api/voice_sample/" + v.id, { headers: apiHeaders() });
      if (!r.ok) throw new Error("sample " + r.status);
      this.audio.playNarration(await r.arrayBuffer());
    } catch { /* sample unavailable :  selection still applied */ }
  }
}
