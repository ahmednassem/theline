"""Geometry check :  the free, deterministic gate of pipeline v2.2.

Python mirror of the browser layout math (UI/js/dsl.js + hershey.js), plus
the v2.2 Scene-State Model (§8): a persistent registry of what is on screen
across scenes, named layout slots with a one-occupant rule, remove-then-add
(replace) semantics, arrow path checks, effect anti-repeat, and the
no-symbol-before-its-beat gate (§9.4).

Auto-fixes what it can; everything else becomes a precise structured reason
back to the create step. No API calls. Ever.
"""
import ast
import math
import re
from collections import deque
from pathlib import Path

FONT_PATH = Path(__file__).parent.parent / "UI" / "lib" / "futural.jhf"

# must match dsl.js
AREA = {"x0": -1.15, "x1": 1.15, "y0": -0.42, "y1": 0.72}
DEFAULT_ASPECT = 1.78  # the browser's world x range is exactly +-aspect


def screen_for(aspect=DEFAULT_ASPECT):
    """Usable screen box for the caller's real window aspect ratio."""
    ax = max(1.0, min(2.4, float(aspect))) - 0.06
    return {"x0": -ax, "x1": ax, "y0": -0.9, "y1": 0.9}


def slots_for(aspect=DEFAULT_ASPECT):
    """Fixed layout slots (§8.4), sized to the caller's real window."""
    a = max(1.0, min(2.4, float(aspect)))
    bx = min(1.25, a - 0.3)  # half-width of the horizontal bands
    dx = a - 0.12            # outer edge for the diagram halves
    return {
        "title_band":      {"x0": -bx, "x1": bx, "y0": 0.74,  "y1": 0.88,  "at": [0.0, 0.79]},
        "diagram_left":    {"x0": -dx, "x1": -0.1, "y0": -0.35, "y1": 0.6, "at": [-(0.1 + dx) / 2, 0.12]},
        "diagram_right":   {"x0": 0.1, "x1": dx, "y0": -0.35, "y1": 0.6,   "at": [(0.1 + dx) / 2, 0.12]},
        "formula_band":    {"x0": -bx, "x1": bx, "y0": -0.62, "y1": -0.45, "at": [0.0, -0.55]},
        "conclusion_band": {"x0": -bx, "x1": bx, "y0": -0.86, "y1": -0.66, "at": [0.0, -0.78]},
    }


def fallback_spots(aspect=DEFAULT_ASPECT):
    """Candidate label positions when relocating same-scene collisions."""
    ax = max(1.0, min(2.4, float(aspect))) - 0.35
    return [
        [0.9, 0.8], [-0.9, 0.8], [0.0, 0.82], [0.9, -0.7], [-0.9, -0.7],
        [0.0, -0.72], [ax, 0.45], [-ax, 0.45], [ax, -0.3], [-ax, -0.3],
    ]


# defaults kept for callers that don't care about aspect
SCREEN = screen_for()
SLOTS_DEF = slots_for()

EFFECT_PALETTE = [
    "side-by-side highlight (emphasize both, no arrow)",
    "color-match tint (same color on both)",
    "direct morph",
    "checkmark-and-fade (fade old, write new)",
    "converging arrows",
]


def new_registry():
    """Empty scene-state registry (§8.2)."""
    return {"elements": [], "frame": None, "last_effect": None, "counter": 0}


# ------------------------------------------------------------------ font
_GLYPHS = None


def _font():
    global _GLYPHS
    if _GLYPHS is not None:
        return _GLYPHS
    raw = FONT_PATH.read_text()
    lines = [l.rstrip("\r") for l in raw.split("\n") if l]
    records = []
    cur = None
    need = 0
    for line in lines:
        if cur is None:
            need = int(line[5:8]) * 2 - 2
            cur = line[8:]
        else:
            cur += line
        if len(cur) >= need + 2:
            records.append(cur)
            cur = None
    R = ord("R")
    _GLYPHS = {}
    for idx, rec in enumerate(records):
        ch = chr(32 + idx)
        pts = []
        i = 2
        while i + 1 < len(rec):
            if not (rec[i] == " " and rec[i + 1] == "R"):
                pts.append((ord(rec[i]) - R, ord(rec[i + 1]) - R))
            i += 2
        _GLYPHS[ch] = {
            "left": ord(rec[0]) - R,
            "right": ord(rec[1]) - R,
            "pts": pts,
        }
    return _GLYPHS


def measure_text(text, x, y, size, anchor="center"):
    """Bounding box of a Hershey-rendered string. Mirrors textStrokes()."""
    g = _font()
    s = size / 21.0
    width = 0.0
    for ch in text:
        gl = g.get(ch) or g.get("?")
        width += (gl["right"] - gl["left"]) * s
    x0 = x - width / 2 if anchor == "center" else x
    ymin, ymax = y, y
    for ch in text:
        gl = g.get(ch) or g.get("?")
        for (_, gy) in gl["pts"]:
            wy = y - gy * s
            ymin = min(ymin, wy)
            ymax = max(ymax, wy)
    if ymin == ymax:  # all-space string
        ymin, ymax = y - size * 0.5, y + size * 0.5
    return {"x0": x0, "x1": x0 + width, "y0": ymin, "y1": ymax}


def text_width(text, size):
    g = _font()
    s = size / 21.0
    return sum((g.get(ch, g["?"])["right"] - g.get(ch, g["?"])["left"]) * s for ch in text)


# ------------------------------------------------------------------ math
_FUNCS = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sqrt": math.sqrt, "abs": abs, "exp": math.exp, "log": math.log,
    "floor": math.floor, "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e}
_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load,
    ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
    ast.USub, ast.UAdd,
)


def compile_expr(src):
    """Safe f(x) from an expression string. Raises ValueError if invalid."""
    try:
        tree = ast.parse(str(src).replace("^", "**"), mode="eval")
    except SyntaxError as e:
        raise ValueError(f"syntax error: {e.msg}")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"disallowed construct {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
                raise ValueError("unknown function")
        if isinstance(node, ast.Name) and node.id not in _FUNCS and node.id != "x" and node.id not in _CONSTS:
            raise ValueError(f"unknown name '{node.id}'")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ValueError("non-numeric constant")
    code = compile(tree, "<fn>", "eval")
    env = {"__builtins__": {}}
    scope = dict(_FUNCS)
    scope.update(_CONSTS)

    def f(x):
        try:
            return float(eval(code, env, {**scope, "x": x}))
        except Exception:
            return float("nan")

    return f


# ------------------------------------------------------------------ frame
def make_frame(x_range, y_range):
    x0, x1 = x_range
    y0, y1 = y_range
    return {"x0": x0, "x1": x1, "y0": y0, "y1": y1}


def map_x(frame, x):
    return AREA["x0"] + (x - frame["x0"]) / (frame["x1"] - frame["x0"]) * (AREA["x1"] - AREA["x0"])


def map_y(frame, y):
    return AREA["y0"] + (y - frame["y0"]) / (frame["y1"] - frame["y0"]) * (AREA["y1"] - AREA["y0"])


def map_pos(frame, p):
    if frame:
        return [map_x(frame, p[0]), map_y(frame, p[1])]
    return [float(p[0]), float(p[1])]


# ------------------------------------------------------------------ boxes
def _pad(b, p):
    return {"x0": b["x0"] - p, "y0": b["y0"] - p, "x1": b["x1"] + p, "y1": b["y1"] + p}


def _boxes_overlap(a, b, pad=0.0):
    a = _pad(a, pad)
    return not (a["x1"] < b["x0"] or b["x1"] < a["x0"] or a["y1"] < b["y0"] or b["y1"] < a["y0"])


def _in_screen(b, pad=0.0, screen=None):
    s = screen or SCREEN
    return (b["x0"] >= s["x0"] - pad and b["x1"] <= s["x1"] + pad
            and b["y0"] >= s["y0"] - pad and b["y1"] <= s["y1"] + pad)


def _pts_in_box(pts, b, pad=0.03):
    bb = _pad(b, pad)
    return any(bb["x0"] <= px <= bb["x1"] and bb["y0"] <= py <= bb["y1"] for px, py in pts)


def _point_in_box(p, b, pad=0.02):
    bb = _pad(b, pad)
    return bb["x0"] <= p[0] <= bb["x1"] and bb["y0"] <= p[1] <= bb["y1"]


def _seg_hits_box(p0, p1, b, pad=0.01):
    """Segment vs AABB (slab test)."""
    bb = _pad(b, pad)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    tmin, tmax = 0.0, 1.0
    for d, lo, hi, o in ((dx, bb["x0"], bb["x1"], p0[0]), (dy, bb["y0"], bb["y1"], p0[1])):
        if abs(d) < 1e-12:
            if o < lo or o > hi:
                return False
        else:
            t1, t2 = (lo - o) / d, (hi - o) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return False
    return True


def _collides(bbox, elements, pad=0.02):
    for el in elements:
        if el["kind"] == "curve":
            if _pts_in_box(el["pts"], bbox, pad + 0.02):
                return el
        elif el["kind"] in ("text", "shape"):
            if _boxes_overlap(bbox, el["bbox"], pad):
                return el
    return None


# ------------------------------------------------------------------ check
# ops that place something on screen get a server-assigned unique id when
# missing :  the id is written INTO the streamed op, so the browser and the
# registry can never disagree about what an element is called
_NEEDS_ID = ("plot", "write", "circle", "arrow", "line")


def _default_id(op):
    t = op.get("op")
    if op.get("id"):
        return str(op["id"])
    if t == "axes":
        return "axes"
    return t or "?"


def _remove_id(elements, oid):
    return [e for e in elements if e["id"] != oid]


def _symbol_violation(text, future_symbols, scene_no):
    if not future_symbols:
        return None
    low = text.lower()
    for sym, scn in future_symbols.items():
        s = str(sym).strip().lower()
        if len(s) < 2:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", low):
            return f"symbol '{sym}' is introduced in scene {scn} :  scene {scene_no} must not show it yet"
    return None


def check_and_fix(ops, registry=None, scene_no=1, future_symbols=None, aspect=DEFAULT_ASPECT):
    """Validate + auto-fix one scene's ops against the live scene state.

    Returns {ok, ops, reasons, soft, fixes, registry}. `registry` is the
    would-be state AFTER this scene :  the caller commits it only when the
    scene is actually published. `soft` are style-rule violations (effect
    anti-repeat) worth one retry but not worth blocking a scene over.
    """
    reg = registry or new_registry()
    frame = dict(reg["frame"]) if reg.get("frame") else None
    elements = [dict(e) for e in reg.get("elements", [])]
    counter = int(reg.get("counter", 0))
    screen = screen_for(aspect)
    slots_def = slots_for(aspect)
    spots = fallback_spots(aspect)
    reasons = []
    soft = []
    fixes = []
    out = []
    effect = None

    def occupied(slot):
        return next((e for e in elements if e.get("slot") == slot), None)

    work = deque(ops or [])
    while work:
        raw = work.popleft()
        if not isinstance(raw, dict):
            fixes.append("dropped non-object op")
            continue
        op = dict(raw)
        t = op.get("op")
        if t in _NEEDS_ID and not op.get("id"):
            counter += 1
            op["id"] = f"{t}-{counter}"
        oid = _default_id(op)

        # --- remove-then-add: replace translates to fade + draw (§8.3)
        if t == "replace":
            old = str(op.get("old", ""))
            withop = op.get("with")
            old_el = next((e for e in elements if e["id"] == old), None)
            if old_el is None:
                fixes.append(f"replace: unknown old id '{old}', treating as plain add")
            else:
                out.append({"op": "fade", "id": old})
                if isinstance(withop, dict) and not withop.get("slot") and not withop.get("at") and old_el.get("slot"):
                    withop = dict(withop)
                    withop["slot"] = old_el["slot"]
                elements = _remove_id(elements, old)
            if isinstance(withop, dict):
                work.appendleft(withop)
            continue

        if t == "axes":
            frame = make_frame(op.get("x") or [-1, 1], op.get("y") or [-1, 1])
            elements = _remove_id(elements, oid)  # same-id redraw replaces
            out.append(op)

        elif t == "plot":
            if frame is None:
                dom = op.get("domain") or [-1, 1]
                frame = make_frame(dom, op.get("range") or [-1.2, 1.2])
            try:
                f = compile_expr(op.get("fn", ""))
            except ValueError as e:
                reasons.append(f"plot fn '{op.get('fn')}' rejected: {e}")
                continue
            d0, d1 = op.get("domain") or [frame["x0"], frame["x1"]]
            pts = []
            valid = 0
            for i in range(101):
                x = d0 + (d1 - d0) * i / 100
                y = f(x)
                if math.isfinite(y):
                    valid += 1
                else:
                    y = 0.0
                y = max(frame["y0"], min(frame["y1"], y))
                pts.append((map_x(frame, x), map_y(frame, y)))
            if valid < 20:
                reasons.append(f"plot fn '{op.get('fn')}' is invalid almost everywhere on [{d0}, {d1}]")
                continue
            elements = _remove_id(elements, oid)
            elements.append({"kind": "curve", "id": oid, "scene": scene_no, "pts": pts, "slot": None,
                             "content": str(op.get("fn", "")),
                             "bbox": {"x0": min(p[0] for p in pts), "x1": max(p[0] for p in pts),
                                      "y0": min(p[1] for p in pts), "y1": max(p[1] for p in pts)}})
            out.append(op)

        elif t == "write":
            text = str(op.get("text", ""))
            clean = "".join(c for c in text if 32 <= ord(c) < 127)
            if clean != text:
                fixes.append(f"stripped non-ascii from text '{text[:20]}'")
                op["text"] = text = clean
            if not text:
                fixes.append("dropped empty write")
                continue
            if len(text) > 26:
                reasons.append(f"text '{text[:26]}...' too long ({len(text)} chars, max 26)")
                continue
            viol = _symbol_violation(text, future_symbols, scene_no)
            if viol:
                reasons.append(viol)
                continue
            size = float(op.get("size") or 0.09)
            slot = op.pop("slot", None)
            elements = _remove_id(elements, oid)  # same-id redraw replaces

            if slot:
                sd = slots_def.get(slot)
                if not sd:
                    fixes.append(f"unknown slot '{slot}' :  placed freely")
                    slot = None
                else:
                    occ = occupied(slot)
                    if occ:
                        reasons.append(
                            f"slot '{slot}' is occupied by '{occ['id']}' (scene {occ['scene']}) :  "
                            f"use {{\"op\":\"replace\",\"old\":\"{occ['id']}\",\"with\":{{...}}}} or fade it first"
                        )
                        continue
                    # shrink until it fits the slot width
                    while size > 0.05 and text_width(text, size) > (sd["x1"] - sd["x0"]) - 0.1:
                        size *= 0.85
                    op["size"] = round(size, 3)
                    op["anchor"] = "center"
                    x, y = sd["at"]
            if not slot:
                at = op.get("at") or [0, 0.8]
                x, y = float(at[0]), float(at[1])

            bbox = measure_text(text, x, y, size, op.get("anchor", "center"))
            dx = max(0.0, screen["x0"] - bbox["x0"]) + min(0.0, screen["x1"] - bbox["x1"])
            dy = max(0.0, screen["y0"] - bbox["y0"]) + min(0.0, screen["y1"] - bbox["y1"])
            if dx or dy:
                x += dx
                y += dy
                bbox = measure_text(text, x, y, size, op.get("anchor", "center"))
                fixes.append(f"moved off-screen label '{text}' into view")
            offender = _collides(bbox, elements)
            if offender and offender["scene"] < scene_no:
                # cross-scene collision: never silently shuffle old content (§8.3)
                reasons.append(
                    f"'{text}' would overlap '{offender['id']}' from scene {offender['scene']} :  "
                    f"use {{\"op\":\"replace\",\"old\":\"{offender['id']}\",\"with\":{{...}}}} "
                    f"or {{\"op\":\"fade\",\"id\":\"{offender['id']}\"}} first, or pick a free slot"
                )
                continue
            if offender:
                placed = False
                for sx, sy in spots:
                    cand = measure_text(text, sx, sy, size, "center")
                    if _in_screen(cand, screen=screen) and not _collides(cand, elements):
                        x, y = sx, sy
                        bbox = cand
                        op["anchor"] = "center"
                        fixes.append(f"relocated label '{text}' (overlapped {offender['kind']} '{offender['id']}') to [{sx}, {sy}]")
                        placed = True
                        break
                if not placed:
                    reasons.append(
                        f"label '{text}' overlaps {offender['kind']} '{offender['id']}' and no free spot fits :  "
                        f"use fewer/shorter labels"
                    )
                    continue
            op["at"] = [round(x, 3), round(y, 3)]
            elements.append({"kind": "text", "id": oid, "scene": scene_no, "bbox": bbox,
                             "slot": slot, "content": text})
            out.append(op)

        elif t == "circle":
            slot = op.pop("slot", None)
            if slot and slot in slots_def:
                occ = occupied(slot)
                if occ:
                    reasons.append(f"slot '{slot}' is occupied by '{occ['id']}' (scene {occ['scene']}) :  replace or fade it first")
                    continue
                sd = slots_def[slot]
                op["at"] = sd["at"]
                cx, cy = sd["at"]
                r = min(float(op.get("r") or 0.3), (sd["y1"] - sd["y0"]) / 2, (sd["x1"] - sd["x0"]) / 2)
                op["r"] = round(r, 3)
            else:
                slot = None
                cx, cy = map_pos(frame, op.get("at") or [0, 0.15])
                r = float(op.get("r") or 0.3)
                if r > 0.6:
                    op["r"] = r = 0.6
                    fixes.append("clamped oversized circle radius to 0.6")
            bbox = {"x0": cx - r, "x1": cx + r, "y0": cy - r, "y1": cy + r}
            if not _in_screen(bbox, pad=0.05, screen=screen):
                reasons.append(
                    f"circle '{oid}' at screen ({cx:.2f}, {cy:.2f}) r={r} leaves the screen "
                    f"(bounds x {screen['x0']:.2f}..{screen['x1']:.2f}, y {screen['y0']}..{screen['y1']})"
                )
                continue
            elements = _remove_id(elements, oid)
            elements.append({"kind": "shape", "id": oid, "scene": scene_no, "bbox": bbox,
                             "slot": slot, "content": "circle"})
            out.append(op)

        elif t in ("arrow", "line"):
            if not op.get("from") or not op.get("to"):
                fixes.append(f"dropped {t} without from/to")
                continue
            f0 = map_pos(frame, op["from"])
            t0 = map_pos(frame, op["to"])
            clamped = False
            for p in (f0, t0):
                nx = max(screen["x0"], min(screen["x1"], p[0]))
                ny = max(screen["y0"], min(screen["y1"], p[1]))
                if nx != p[0] or ny != p[1]:
                    p[0], p[1] = nx, ny
                    clamped = True
            if clamped:
                fixes.append(f"clamped {t} '{oid}' endpoints into the screen")
                if frame:
                    inv_x = lambda wx: frame["x0"] + (wx - AREA["x0"]) / (AREA["x1"] - AREA["x0"]) * (frame["x1"] - frame["x0"])
                    inv_y = lambda wy: frame["y0"] + (wy - AREA["y0"]) / (AREA["y1"] - AREA["y0"]) * (frame["y1"] - frame["y0"])
                    op["from"] = [round(inv_x(f0[0]), 3), round(inv_y(f0[1]), 3)]
                    op["to"] = [round(inv_x(t0[0]), 3), round(inv_y(t0[1]), 3)]
                else:
                    op["from"] = [round(f0[0], 3), round(f0[1], 3)]
                    op["to"] = [round(t0[0], 3), round(t0[1], 3)]
            if t == "arrow":
                effect = "converging arrows"
                # §8.5: the path may not cross any bbox it is not pointing at
                blockers = [
                    e for e in elements
                    if e["kind"] in ("text", "shape")
                    and not _point_in_box(f0, e["bbox"]) and not _point_in_box(t0, e["bbox"])
                    and _seg_hits_box(f0, t0, e["bbox"])
                ]
                if blockers:
                    b = blockers[0]
                    reasons.append(
                        f"arrow '{oid}' path crosses {b['kind']} '{b['id']}' (scene {b['scene']}) :  "
                        f"reroute it, move one endpoint, or use a different comparison effect"
                    )
                    continue
            bbox = {"x0": min(f0[0], t0[0]), "x1": max(f0[0], t0[0]),
                    "y0": min(f0[1], t0[1]), "y1": max(f0[1], t0[1])}
            elements = _remove_id(elements, oid)
            elements.append({"kind": "shape", "id": oid, "scene": scene_no, "bbox": bbox,
                             "slot": None, "content": t})
            out.append(op)

        elif t in ("emphasize", "fade"):
            if not any(e["id"] == op.get("id") for e in elements):
                fixes.append(f"dropped {t} referencing unknown id '{op.get('id')}'")
                continue
            if t == "fade":
                elements = _remove_id(elements, op["id"])
            out.append(op)

        elif t == "morph":
            effect = effect or "direct morph"
            out.append(op)

        elif t == "clear":
            frame = None
            elements = []
            out.append(op)

        elif t == "pause":
            out.append(op)

        else:
            fixes.append(f"dropped unknown op '{t}'")

    # §8.5 anti-repeat: same comparison effect two scenes in a row
    if effect and effect == reg.get("last_effect"):
        try:
            from . import knowledge
            alts = [e["name"] for e in knowledge.effects()] or EFFECT_PALETTE
        except Exception:
            alts = EFFECT_PALETTE
        soft.append(
            f"effect '{effect}' was already used in the previous scene :  pick a different one: "
            + "; ".join(e for e in alts if not e.startswith(effect.split(' ')[0]))
        )

    new_reg = {
        "elements": elements,
        "frame": frame,
        "last_effect": effect if effect else None,
        "counter": counter,
    }
    return {"ok": not reasons, "ops": out, "reasons": reasons, "soft": soft,
            "fixes": fixes, "registry": new_reg}


def describe_registry(registry):
    """Compact human-readable 'ON SCREEN RIGHT NOW' block for create calls."""
    els = registry.get("elements", [])
    if not els:
        return "The screen is currently EMPTY."
    lines = []
    for e in els:
        b = e["bbox"]
        loc = f"slot {e['slot']}" if e.get("slot") else f"bbox x {b['x0']:.2f}..{b['x1']:.2f}, y {b['y0']:.2f}..{b['y1']:.2f}"
        content = f" \"{e['content']}\"" if e.get("content") else ""
        lines.append(f"- {e['kind']} '{e['id']}'{content} ({loc}, since scene {e['scene']})")
    txt = "ON SCREEN RIGHT NOW:\n" + "\n".join(lines)
    if registry.get("frame"):
        f = registry["frame"]
        txt += f"\nActive plot frame: x [{f['x0']}, {f['x1']}], y [{f['y0']}, {f['y1']}]"
    if registry.get("last_effect"):
        txt += f"\nLast comparison effect used: {registry['last_effect']} (do NOT reuse it this scene)"
    return txt
