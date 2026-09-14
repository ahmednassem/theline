"""Pipeline v2: plan-first + neuro-symbolic.

One Planner call outlines the whole answer. Each scene is then generated
with its plan context, gated by the free geometry check (auto-fix / precise
retry reasons, max 3 rounds), optionally judged by an LLM check when the
scene is novel, and published by the brain :  which force-picks the best
candidate rather than stalling when the viewer is about to starve.

Output: NDJSON lines {narration, ops, meta:{scene, of, flagged?, filler?}}.
"""
import json
import re
import time

from . import geometry, knowledge, llm

MAX_REVISIONS = 3
MAX_WAIT = 14.0  # seconds since last publish before force-pick pressure
STARVE_MARGIN = 4.0  # viewer has < this many seconds of content left


def _parse_json(text):
    """Parse a JSON object out of an LLM reply (tolerates fences/preambles)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _history(messages, extra_user):
    """History with the pipeline instruction merged into the last user turn."""
    msgs = [
        {"role": m["role"], "content": str(m["content"])}
        for m in messages[-24:]
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")
    ]
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1] = {"role": "user", "content": msgs[-1]["content"] + "\n\n---\n" + extra_user}
    else:
        msgs.append({"role": "user", "content": extra_user})
    return msgs


# ------------------------------------------------------------------ prompts
DSL_SPEC = """Available ops (pure data, executed in narration order):
- {"op":"axes", "x":[x0,x1], "y":[y0,y1]}  coordinate frame for plots
- {"op":"plot", "fn":"sin(x)*exp(-x/4)", "domain":[a,b], "id":"name", "color":"blue"}  requires axes first. fn syntax: variable x, functions sin cos tan asin acos atan sqrt abs exp log floor ceil, constants pi e, operators + - * / ^
- {"op":"write", "text":"y = sin(x)", "slot":"formula_band", "size":0.09, "color":"yellow", "id":"name"}  handwritten text, ASCII only, max ~24 chars. PREFER "slot"; "at":[x,y] screen coords only for annotations near curves
- {"op":"circle", "at":[x,y], "r":0.07, "color":"green", "id":"name"}  r in screen units (0.05-0.1 marks a point); may also use "slot":"diagram_left"
- {"op":"arrow", "from":[x,y], "to":[x,y], "color":"red", "id":"name"}  the path must not cross unrelated elements
- {"op":"line", "from":[x,y], "to":[x,y], "color":"white", "id":"name"}
- {"op":"replace", "old":"existing_id", "with":{...any draw op...}}  REMOVE-THEN-ADD: the old element fades, the new one takes its place. THE way to update text/formulas
- {"op":"emphasize", "id":"name"}  pulse an existing element
- {"op":"fade", "id":"name"}  fade one element out
- {"op":"clear"}  fade everything out (only between unrelated diagrams)
- {"op":"pause", "sec":0.5}

LAYOUT SLOTS with their exact boxes (one occupant each :  adding into an occupied slot is REJECTED, use "replace"):
{slot_boxes}
Plots+axes own the middle "stage" (x -1.15..1.15, y -0.42..0.72).

Coordinates: "at" for write is SCREEN coords: x {xmin}..{xmax}, y -0.9..0.9, origin center :  THIS window is exactly that wide, nothing outside it is visible. After "axes" exist, circle/arrow/line positions are PLOT coordinates (same units as the axes ranges) :  use them to mark points ON curves, e.g. the peak of sin at [1.57, 1].
Colors: white grey blue yellow green red purple teal. Defaults are 3blue1brown-like already.

{effects}"""

FALLBACK_EFFECTS = ("COMPARISON EFFECTS palette (never the same one twice in a row): "
                    "side-by-side highlight (emphasize both), color-match tint, "
                    "checkmark-and-fade, converging arrows.")


def _effects_line():
    fx = knowledge.effects()
    if not fx:
        return FALLBACK_EFFECTS
    lines = "\n".join(f"- {e['name']}: {e['how']}" for e in fx)
    return ("VISUAL EFFECTS palette, learned from 3b1b's real videos "
            "(never the same one twice in a row):\n" + lines)


def dsl_spec(aspect):
    slots = geometry.slots_for(aspect)
    screen = geometry.screen_for(aspect)
    boxes = "\n".join(
        f"- {name}: x {s['x0']:.2f}..{s['x1']:.2f}, y {s['y0']:.2f}..{s['y1']:.2f}"
        for name, s in slots.items()
    )
    return (DSL_SPEC
            .replace("{slot_boxes}", boxes)
            .replace("{xmin}", f"{screen['x0']:.2f}")
            .replace("{xmax}", f"{screen['x1']:.2f}")
            .replace("{effects}", _effects_line()))

PLANNER_SYSTEM = """You are the Planner of "The Line", a voice + line-art explainer. Given a conversation, produce the outline of the whole answer BEFORE any scene is generated. Respond with ONLY a JSON object, no markdown:

{"depth": "surface" | "deep" | "detailed",
 "scenes": [{"purpose": "one line: what this scene achieves",
             "beat": "what is narrated and shown, concretely",
             "continuity": "what carries over from previous scenes / callbacks",
             "introduces": ["pi", "C = pi d"]}]}

DEPTH :  {depth_rule}
- surface: intuition only, ZERO symbols or formulas on screen. Beats: hook, manipulation, anchor.
- deep: mechanism shown visually first; a formula may appear only AFTER the visual reason for it. All five beats.
- detailed: all of deep, plus formal statement and a historical/derivation beat :  still animated, never a wall of text.

Structure every explanation on the five-beat arc: hook (why care) -> concrete case (real numbers) -> manipulation (the visual move that shows the mechanism) -> generalize (name it, formula) -> anchor (one memorable takeaway). Depth decides how many beats you include and how far each goes :  deeper ADDS beats, never re-shoots earlier ones.

Rules:
- {limit} scenes total. One idea per scene. Order matters: build understanding step by step.
- Scenes must form ONE coherent piece: later scenes reuse what is already on screen ("the curve we just drew") instead of redrawing it.
- "introduces": the symbols/formulas this scene is allowed to put ON SCREEN for the first time (e.g. "pi", "sin", "C = pi d"). Empty list if none. A symbol may NEVER appear on screen before its introducing scene :  plan accordingly.
- Think about what is VISUAL per scene (plot, shapes, labels) vs what is only narrated.
- Keep each field to one or two short sentences."""

CREATE_SYSTEM = """You are the scene generator of "The Line" :  a minimal AI whose whole interface is one glowing line that narrates and draws, 3blue1brown style.

{dsl}

Respond with ONLY one JSON object, no markdown:
{{"narration": "one to three spoken sentences", "ops": [...], "novel": false}}

Rules:
- You are generating EXACTLY ONE scene of a planned multi-scene answer. Follow your beat; do not repeat previous scenes or steal the next scene's content.
- READ the "ON SCREEN RIGHT NOW" state you are given: build on what exists, never draw on top of it. To change existing text/formulas use "replace". Adding into an occupied slot is rejected.
- Narration is spoken aloud: conversational, clear (say "x squared", write "x^2").
- 0 to 5 ops. Simple narration-only scenes are fine (ops: []).
- Start with {{"op":"clear"}} ONLY if this scene needs a fresh diagram unrelated to what is currently on screen.
- Only put symbols/formulas on screen that your scene's "may introduce" list (or an earlier scene) allows.
- Set "novel": true ONLY if the layout is unusual/freeform (not a standard plot+labels or a few shapes) and deserves a style review.
- ASCII only in "text". Narration is ALWAYS English, even when the user asks in another language. On-screen "text" is ALWAYS English ASCII."""

CHECK_SYSTEM = """You review ONE scene of a line-art explainer for subjective quality only (geometry is already verified). Judge: does the narration match the visuals, is the pacing sane (not cramming), does it fit its beat in the plan? Respond with ONLY JSON: {"score": 0-10, "issues": "short actionable reason if score < 7, else empty"}"""

FIX_SYSTEM = """You are the scene FIXER of "The Line". You receive one scene (narration + ops) that failed a deterministic check, together with the EXACT violations and the current screen state. Produce the SAME scene with the smallest possible change that resolves every violation.

{dsl}

Respond with ONLY one JSON object, no markdown:
{{"narration": "...", "ops": [...], "novel": false}}

Rules:
- Change ONLY what the violations require: keep the narration identical, keep every op that was not named in a violation byte-for-byte identical.
- Typical fixes: move a label to a free slot or free coordinates, add a {{"op":"replace","old":"...","with":{{...}}}} for content that would overlap something older, reroute or drop a blocked arrow, remove an early symbol, pick a different comparison effect.
- Do not add new content beyond what fixing requires."""


# ------------------------------------------------------------------ steps
def _style_block():
    b = knowledge.bible()
    if not b:
        return ""
    return ("\n\nTHE CRAFT (distilled from 3Blue1Brown's real videos :  follow it):\n" + b
            + "\n\nIMPORTANT: you draw with the limited line-art DSL above :  no continuous"
            " morphing, camera moves, or sliding animations. Express those ideas with"
            " sequenced draws, replace, fade and emphasize instead. Never plan a scene"
            " the DSL cannot literally draw.")


def make_plan(messages, mode, depth="auto", cfg=None):
    if mode == "quick":
        limit = "1 to 3"
    elif mode == "video":
        limit = "4 to 10"
    else:  # auto :  the planner judges what the question deserves
        limit = ("1 to 8 :  judge what the question deserves: a trivial or factual "
                 "question gets 1-2 scenes, a rich conceptual topic gets a full arc")
    if depth in ("surface", "deep", "detailed"):
        depth_rule = f'the user requires depth "{depth}". Set it and plan for it.'
    else:
        depth_rule = "choose the level this question deserves:"
    question = next((m.get("content", "") for m in reversed(messages)
                     if m.get("role") == "user"), "")
    instruction = "Plan the scenes for the answer to my last question."
    exemplars = knowledge.exemplar_block(question)
    if exemplars:
        instruction += "\n\n" + exemplars
    txt = llm.complete(PLANNER_SYSTEM.replace("{limit}", limit).replace("{depth_rule}", depth_rule)
                  + _style_block(),
                  _history(messages, instruction),
                  max_tokens=1800, cfg=cfg)
    obj = _parse_json(txt)
    scenes = [s for s in (obj.get("scenes") or []) if isinstance(s, dict)][:10]
    if not scenes:
        raise ValueError("empty plan")
    plan_depth = obj.get("depth") if obj.get("depth") in ("surface", "deep", "detailed") else "deep"
    if depth in ("surface", "deep", "detailed"):
        plan_depth = depth
    return scenes, plan_depth


def future_symbol_map(plan, idx):
    """symbol -> scene number that introduces it, for scenes AFTER idx."""
    seen = set()
    for s in plan[:idx + 1]:
        for sym in s.get("introduces") or []:
            seen.add(str(sym).lower())
    future = {}
    for j in range(idx + 1, len(plan)):
        for sym in plan[j].get("introduces") or []:
            if str(sym).lower() not in seen and sym not in future:
                future[str(sym)] = j + 1
    return future


def fix_scene(seg, violations, registry, aspect, cfg=None):
    """Try-and-Fix: patch ONLY the violating ops, keep everything else."""
    system = (FIX_SYSTEM.replace("{dsl}", dsl_spec(aspect))
              .replace("{{", "{").replace("}}", "}")) + _style_block()
    content = "\n\n".join([
        "THE SCENE THAT FAILED:\n" + json.dumps({"narration": seg.get("narration", ""), "ops": seg.get("ops", [])}),
        "VIOLATIONS (every one must be resolved):\n- " + "\n- ".join(violations),
        geometry.describe_registry(registry),
        "Narration is ALWAYS English. On-screen text stays English ASCII.",
    ])
    txt = llm.complete(system, [{"role": "user", "content": content}], max_tokens=1400, cfg=cfg)
    fixed = _parse_json(txt)
    if not isinstance(fixed.get("narration"), str) or not fixed["narration"].strip():
        fixed["narration"] = seg.get("narration", "")
    if not isinstance(fixed.get("ops"), list):
        fixed["ops"] = seg.get("ops", [])
    fixed["novel"] = seg.get("novel", False)
    return fixed


def create_scene(messages, plan, idx, prev_summary, feedback, registry, depth, aspect, cfg=None):
    outline = "\n".join(f"  {i+1}. {s.get('purpose', '')}" for i, s in enumerate(plan))
    intro = plan[idx].get("introduces") or []
    parts = [
        f"THE PLAN ({len(plan)} scenes, depth: {depth}):\n{outline}",
        f"YOU ARE CREATING SCENE {idx+1} of {len(plan)}.",
        f"Beat: {plan[idx].get('beat', '')}",
        f"Continuity: {plan[idx].get('continuity', '')}",
        f"May introduce on screen: {', '.join(intro) if intro else 'nothing new'}.",
        geometry.describe_registry(registry),
    ]
    if prev_summary:
        parts.append(f"Previous scene said: {prev_summary}")
    if idx + 1 < len(plan):
        parts.append(f"Next scene will: {plan[idx+1].get('purpose', '')}")
    if feedback:
        parts.append(f"YOUR PREVIOUS ATTEMPT WAS REJECTED :  fix this precisely: {feedback}")
    system = (CREATE_SYSTEM.replace("{dsl}", dsl_spec(aspect))
              .replace("{{", "{").replace("}}", "}")) + _style_block()
    txt = llm.complete(system, _history(messages, "\n\n".join(parts)), max_tokens=1400, cfg=cfg)
    seg = _parse_json(txt)
    if not isinstance(seg.get("narration"), str) or not seg["narration"].strip():
        raise ValueError("segment missing narration")
    if not isinstance(seg.get("ops"), list):
        seg["ops"] = []
    return seg


def llm_check(seg, scene_plan, cfg=None):
    try:
        txt = llm.complete(CHECK_SYSTEM, [{
            "role": "user",
            "content": json.dumps({
                "beat": scene_plan.get("beat", ""),
                "narration": seg.get("narration", ""),
                "ops": seg.get("ops", []),
            }),
        }], max_tokens=300, cfg=cfg)
        obj = _parse_json(txt)
        score = float(obj.get("score", 7))
        return score >= 7, str(obj.get("issues", ""))
    except Exception:
        return True, ""  # the optional gate must never block the pipeline


def _estimate_duration(seg):
    d = max(1.5, len(seg.get("narration", "")) / 15.0)
    est = {"axes": 1.6, "plot": 2.2, "write": 1.2, "circle": 1.1,
           "arrow": 0.7, "line": 0.5, "clear": 0.7, "pause": 0.8}
    for op in seg.get("ops", []):
        d += est.get(op.get("op"), 0.5) * 0.4  # ops overlap narration
    return d


# ------------------------------------------------------------------ brain
def run(messages, mode="quick", depth="auto", aspect=1.78, cfg=None):
    """Generator: yields NDJSON lines for /api/ask.

    cfg: optional per-request key/provider overrides (bring-your-own-key
    from the hosted UI) :  passed to every LLM call, never stored.
    """
    t_start = time.time()
    try:
        plan, depth = make_plan(messages, mode, depth, cfg=cfg)
    except Exception as e:
        print(f"[pipeline] planner failed ({e}); falling back to single-scene plan")
        last = next((m["content"] for m in reversed(messages)
                     if isinstance(m, dict) and m.get("role") == "user"), "")
        plan = [{"purpose": "answer the question", "beat": str(last)[:300], "continuity": ""}]
        depth = "surface"
    n = len(plan)
    print(f"[pipeline] plan ready in {time.time()-t_start:.1f}s: {n} scenes ({mode}, depth={depth})")

    published_end = time.time()  # virtual playback clock
    last_publish = time.time()
    prev_summary = ""
    registry = geometry.new_registry()  # §8.2: ground truth of the screen

    for i, scene_plan in enumerate(plan):
        seg = None
        seg_registry = None
        best = None  # best geometry-passing candidate (style-rejected)
        best_registry = None
        violations = None  # structured reasons for the targeted fix prompt
        last_cand = None
        forced = False
        future_syms = future_symbol_map(plan, i)

        for attempt in range(MAX_REVISIONS):
            starving = (published_end - time.time() < STARVE_MARGIN
                        and time.time() - last_publish > MAX_WAIT)
            if starving and best is not None:
                forced = True
                break
            try:
                if attempt == 0 or last_cand is None:
                    cand = create_scene(messages, plan, i, prev_summary,
                                        "; ".join(violations) if violations else None,
                                        registry, depth, aspect, cfg=cfg)
                else:
                    # Try-and-Fix: patch only the violating ops of the last candidate
                    cand = fix_scene(last_cand, violations, registry, aspect, cfg=cfg)
            except Exception as e:
                violations = [f"generation failed: {e}"]
                continue
            last_cand = cand
            res = geometry.check_and_fix(cand.get("ops"), registry,
                                         scene_no=i + 1, future_symbols=future_syms,
                                         aspect=aspect)
            if res["fixes"]:
                print(f"[pipeline] scene {i+1} auto-fixes: {res['fixes']}")
            if not res["ok"]:
                violations = res["reasons"]
                print(f"[pipeline] scene {i+1} attempt {attempt+1} rejected: {violations}")
                continue
            cand["ops"] = res["ops"]
            if res["soft"] and attempt == 0:
                # style rule (effect anti-repeat): worth exactly one targeted fix
                best, best_registry = cand, res["registry"]
                violations = ["style rule: " + "; ".join(res["soft"])]
                print(f"[pipeline] scene {i+1} attempt {attempt+1} soft-retry: {res['soft']}")
                continue
            if cand.get("novel"):
                ok, issues = llm_check(cand, scene_plan, cfg=cfg)
                if not ok:
                    best, best_registry = cand, res["registry"]
                    violations = ["style check: " + issues]
                    print(f"[pipeline] scene {i+1} attempt {attempt+1} style-rejected: {issues}")
                    continue
            seg = cand
            seg_registry = res["registry"]
            break

        meta = {"scene": i + 1, "of": n}
        if seg is None:
            if best is not None:
                seg, seg_registry = best, best_registry
                meta["flagged"] = True
                print(f"[pipeline] FORCED PICK scene={i+1} reason={'starvation' if forced else 'max revisions'} "
                      f"queue_ahead={max(0, published_end - time.time()):.1f}s kind=flagged")
            else:
                seg = {"narration": scene_plan.get("beat") or scene_plan.get("purpose")
                       or "Let me just say this part in words.", "ops": []}
                seg_registry = registry  # screen unchanged
                meta["filler"] = True
                print(f"[pipeline] FORCED PICK scene={i+1} reason=no-candidate "
                      f"queue_ahead={max(0, published_end - time.time()):.1f}s kind=filler")

        yield json.dumps({"narration": seg["narration"], "ops": seg.get("ops", []), "meta": meta}) + "\n"
        registry = seg_registry  # commit the screen state of what was published
        now = time.time()
        published_end = max(published_end, now) + _estimate_duration(seg)
        last_publish = now
        prev_summary = seg["narration"][:160]
