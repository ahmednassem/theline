# Project Handoff :  Manim Video Generation Pipeline

Paste this doc (plus the two companions below) into a new LLM chat to
continue this work without re-explaining everything from scratch.

**Companion docs (share alongside this one):**
- `video-pipeline-architecture-v2.md` :  full architecture: Planner, Create,
  Geometry Check, LLM Check, Brain, Scene Queue, Publisher, frontend buffer
  levels; the Scene-State Model; the 3 explanation depth levels.
- `llm-prompts-and-fix-loop.md` :  the Try-and-Fix Loop and the two
  ready-to-send prompt templates (initial generation + targeted fix).

---

## 1. What this project is

A pipeline that generates long-form educational videos as a sequence of
Manim scenes ("beats"), streamed to a frontend as they're produced, buffered
so playback never stalls waiting on generation. Original components:
`create` (generates a scene), `check` (validates it), `brain` (buffer
manager :  decides when to accept a scene or force-pick under time pressure),
`scene queue`, `publisher`, frontend (buffer levels: normal=3, stable=6,
max=9, full=wait for entire video).

## 2. Where the architecture ended up (v2)

Original flat `create ↔ check` loop was replaced with:
- **Planner** (new, one-time): plans the whole video's scene list/beats
  upfront, so every scene gets prior/next context instead of being
  generated blind.
- **Check split in two**: a free, instant, deterministic **Geometry Check**
  (overlap, bounds, timing :  should be plain code, not an API call) and an
  optional, more expensive **LLM Check** (only for genuinely subjective
  judgment like pacing/feel), invoked only when needed.
- **Scene-State Model**: a live registry of every on-screen object's id,
  bounding box, and layout slot, passed into every generation call. Beats
  must use explicit `REPLACE` / `ADD` / `CLEAR` operations :  never
  free-floating "add this" :  which is what stops old content lingering
  under new content.
- **Fixed layout slots** (title_band, diagram_left, diagram_right,
  formula_band, conclusion_band, etc.) instead of raw coordinates, so two
  elements can't be placed too close together.
- **Effect palette + anti-repeat rule**: multiple comparison effects
  available, can't reuse the same one twice in a row.
- **3 explanation depth levels** (surface / deep / detailed), set once per
  video by the Planner, all built from the same 5-beat pedagogical arc
  (hook → concrete case → manipulation → generalize → anchor), with deeper
  levels adding beats rather than reshooting the video.
- **Try-and-Fix Loop**: failed checks return structured, scoped violation
  reports (exact mobject ids + exact rule broken), and `create` patches
  only those :  not a full regenerate :  capped at 3 rounds.
- **Two separate prompts**: one for initial generation, one for targeted
  fixes (the fix prompt explicitly lists what must stay unchanged).

Full detail, diagrams, and exact prompt text are in the two companion docs.

## 3. Current problem :  unresolved, this is where to pick up

**Symptom:** scenes still come out bad/broken (overlapping elements, one
formula rendered on top of another, layout collisions) even after applying
the v2 prompts with the state registry, layout slots, and remove-then-add
rules.

**Working diagnosis (not yet confirmed):** the Geometry Check is likely not
doing real math. LLMs are unreliable at spatial arithmetic through text no
matter how the prompt is worded :  if "checking" currently means an LLM
reading its own output and judging "does this overlap," that's one guess
reviewing another guess, not a real check. Genuine geometry checking
requires:
1. Parsing or running the generated Manim code to extract each Mobject's
   **actual numeric** position/size (not what the model claims it placed).
2. Running plain AABB overlap math in code on those real numbers.
3. Feeding back the exact overlapping ids/coordinates as a structured
   violation :  a fact, not an opinion.

**Second suspected gap:** the prompt's layout-slots section may be passing
just slot *names* (e.g. "diagram_left") with no actual numeric bounding box
(x/y/w/h). Without real numbers, the model has nothing concrete to place
content against and is effectively still guessing coordinates.

## 4. Open question to answer first, before changing anything else

**Does the current implementation have real code that (a) parses/executes
the generated scene, (b) extracts actual numeric bounding boxes per
Mobject, and (c) runs AABB overlap math in plain code :  or is "checking"
currently entirely prompt-based / LLM self-review?**

This determines everything downstream. If it's prompt-based only, that's
almost certainly the actual bug, independent of how good the generation
prompt itself is.

## 5. Likely next steps once that's confirmed

- If no real geometry math exists yet: build it :  a function that takes the
  rendered/parsed scene, pulls bounding boxes per Mobject (Manim exposes
  this via each Mobject's `get_center()`, `width`, `height`, or
  `get_critical_point` methods), and does plain rectangle-overlap checks.
- Feed the generation prompt **actual numeric coordinates** for each layout
  slot, not just slot names.
- Re-test scene quality with just this fix before touching the Planner,
  depth levels, or Try-and-Fix round count :  this is the highest-leverage
  suspected fix, isolate it first.
