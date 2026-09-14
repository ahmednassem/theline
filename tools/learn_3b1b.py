"""Learn how 3Blue1Brown makes videos :  from his actual published work.

For each pilot video: download the real Manim source (3b1b/videos) and the
transcript (3b1b/captions), then distill BOTH through the LLM into a
"recipe" in our own scene vocabulary. A final pass reads every recipe and
writes the style bible: the universal staging rules the pipeline injects
into every planner/create call.

Usage:
  python tools/learn_3b1b.py          # fetch + distill missing recipes + bible if missing
  python tools/learn_3b1b.py bible    # force-regenerate the style bible
"""
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

# mirror main.py's env loading so server.llm/config find the keys
for _line in (BASE / ".env").read_text().splitlines() if (BASE / ".env").exists() else []:
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        k, v = _line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from server import llm  # noqa: E402
from server.pipeline import _parse_json  # noqa: E402

CACHE = BASE / "data" / "3b1b"
RECIPES = BASE / "knowledge" / "recipes"
BIBLE = BASE / "knowledge" / "style_bible.md"

# verified against the repos' file trees (captions: main, videos: master)
MANIFEST = [
    {"slug": "essence-of-calculus", "cap": "2017/essence-of-calculus",
     "code": ["_2017/eoc/chapter1.py"],
     "tags": "calculus integral derivative area circle pi limit slice"},
    {"slug": "derivatives", "cap": "2017/derivatives",
     "code": ["_2017/eoc/chapter2.py"],
     "tags": "derivative slope velocity rate change tangent dt calculus paradox"},
    {"slug": "eulers-number", "cap": "2017/eulers-number",
     "code": ["_2017/eoc/chapter5.py"],
     "tags": "e euler exponential growth natural log derivative compound"},
    {"slug": "vectors", "cap": "2016/vectors",
     "code": ["_2016/eola/chapter1.py"],
     "tags": "vector linear algebra coordinates arrow scaling addition span"},
    {"slug": "eigenvalues", "cap": "2016/eigenvalues",
     "code": ["_2016/eola/chapter10.py"],
     "tags": "eigenvalue eigenvector matrix transformation linear algebra determinant"},
    {"slug": "neural-networks", "cap": "2017/neural-networks",
     "code": ["_2017/nn/part1.py"],
     "tags": "neural network deep learning neuron layer weights ai machine digit"},
    {"slug": "basel-problem", "cap": "2018/basel-problem",
     "code": ["_2018/basel/basel2.py"],
     "tags": "pi basel sum squares infinite series lighthouse inverse geometry"},
    {"slug": "pi-was-628", "cap": "2018/pi-was-628",
     "code": ["_2018/pi_day.py"],
     "tags": "pi tau circle radians circumference diameter ratio"},
    {"slug": "fourier-series", "cap": "2019/fourier-series",
     "code": ["_2019/diffyq/part4/fourier_series_scenes.py"],
     "tags": "fourier series wave circles rotating sum sine heat frequency"},
    {"slug": "prime-spirals", "cap": "2019/prime-spirals",
     "code": ["_2019/spirals.py"],
     "tags": "prime spiral number theory residue mod pattern polar"},
    {"slug": "bayes-theorem", "cap": "2019/bayes-theorem",
     "code": ["_2019/bayes/part1.py"],
     "tags": "bayes probability evidence hypothesis update prior likelihood"},
    {"slug": "exponential-and-epidemics", "cap": "2020/exponential-and-epidemics",
     "code": ["_2020/covid.py"],
     "tags": "exponential growth epidemic virus doubling rate logistic curve spread"},
]

CODE_CAP = 80_000
TRANSCRIPT_CAP = 22_000


def fetch(repo, branch, path):
    """Raw-URL download with an on-disk cache (no repo cloning)."""
    f = CACHE / repo / path
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    url = f"https://raw.githubusercontent.com/3b1b/{repo}/{branch}/{path}"
    print(f"  fetch {url}")
    with urllib.request.urlopen(url, timeout=60) as r:
        data = r.read()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return data.decode("utf-8", errors="replace")


def strip_code(src):
    """Drop comment lines and squeeze blank runs :  staging info stays."""
    out, blank = [], 0
    for line in src.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        blank = blank + 1 if not s else 0
        if blank > 1:
            continue
        out.append(line)
    return "\n".join(out)


DISTILL_SYSTEM = """You study how Grant Sanderson (3Blue1Brown) constructs an explainer video. You get the video's full narration transcript and the actual Manim source code he wrote for it. Extract HOW the explanation is staged :  the craft, not the topic trivia.

Describe screen placement using ONLY this zone vocabulary: title_band (top), stage (the central area for the main diagram/plot), diagram_left, diagram_right (side-by-side halves), formula_band (under the stage), conclusion_band (bottom).

Respond with ONLY one JSON object:
{
  "title": "...",
  "hook": "how the opening earns attention, one sentence",
  "scenes": [
    {
      "beat": "hook|build|payoff|twist|anchor",
      "purpose": "what this scene accomplishes, short",
      "on_screen": [{"kind": "text|plot|shape|arrow", "zone": "...", "desc": "short"}],
      "transition": "what is removed/kept/transformed entering this scene",
      "narration_gist": "one sentence"
    }
  ],
  "lessons": ["3-6 transferable staging rules this video demonstrates, imperative voice"]
}

Rules: 5-10 scenes covering the video's real arc (merge minor ones). on_screen lists at most 4 items per scene :  what a viewer actually sees at once. Lessons must be about staging/pacing/visual storytelling, never about the specific math topic."""


EFFECTS_SYSTEM = """You have distilled recipes of real 3Blue1Brown videos (scene transitions + staging lessons). Extract his recurring VISUAL EFFECTS as a palette for an AI that draws line-art scenes.

The AI's only drawing operations are: write text, plot function, circle, line, arrow, fade element, replace element, emphasize element, pause. Every effect must be literally achievable with ONLY those :  no morphing, sliding, or camera moves.

Respond with ONLY a JSON array of 8-12 effects:
[{"name": "short-kebab-name", "how": "one sentence: the exact op sequence and what it communicates"}]

Ground every effect in what actually appears in the recipes' transitions. Favor effects for: comparing two things, revealing a result, cancelling terms, shifting attention, closing a loop back to the opening."""

STYLE_SYSTEM = """You have distilled recipes of real 3Blue1Brown videos (staging beats + lessons). Write the STYLE BIBLE: the universal rules of his visual explanation craft, for an AI that draws line-art scenes with narration.

Format: markdown, exactly two sections:
# how 3b1b stages an explanation
(12-18 numbered rules, imperative, each one line, concrete :  placement, pacing, what shares the screen, transitions, when to clear vs keep)
# arc
(5-8 lines describing how a full explanation flows from hook to anchor)

No topic-specific content. No fluff. Under 45 lines total."""


def distill(entry):
    out = RECIPES / f"{entry['slug']}.json"
    if out.exists():
        print(f"- {entry['slug']}: recipe exists, skip")
        return
    print(f"- {entry['slug']}: distilling")
    transcript = fetch("captions", "main", entry["cap"] + "/english/transcript.txt")[:TRANSCRIPT_CAP]
    code = "\n\n".join(strip_code(fetch("videos", "master", p)) for p in entry["code"])[:CODE_CAP]
    content = (f"VIDEO TRANSCRIPT:\n{transcript}\n\n"
               f"MANIM SOURCE CODE HE WROTE FOR IT:\n{code}")
    txt = llm.complete(DISTILL_SYSTEM, [{"role": "user", "content": content}], max_tokens=3000)
    recipe = _parse_json(txt)
    if not recipe.get("scenes"):
        print(f"  !! no scenes parsed for {entry['slug']} :  skipping save")
        return
    recipe["slug"] = entry["slug"]
    recipe["tags"] = entry["tags"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
    print(f"  saved {out.name} ({len(recipe['scenes'])} scenes)")


def make_effects():
    recipes = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RECIPES.glob("*.json"))]
    if not recipes:
        print("no recipes yet :  run distill first")
        return
    material = []
    for r in recipes:
        material.append({
            "title": r.get("title"),
            "transitions": [s.get("transition") for s in r.get("scenes", []) if s.get("transition")],
            "lessons": r.get("lessons", []),
        })
    content = "RECIPE TRANSITIONS AND LESSONS:\n" + json.dumps(material, indent=1)
    txt = llm.complete(EFFECTS_SYSTEM, [{"role": "user", "content": content}], max_tokens=1400)
    m = re.search(r"\[.*\]", txt, re.DOTALL)
    effects = json.loads(m.group(0)) if m else []
    effects = [e for e in effects if isinstance(e, dict) and e.get("name") and e.get("how")]
    if not effects:
        print("!! no effects parsed")
        return
    out = BASE / "knowledge" / "effects.json"
    out.write_text(json.dumps(effects, indent=2), encoding="utf-8")
    print(f"wrote {out} ({len(effects)} effects)")


def make_bible():
    recipes = [json.loads(p.read_text()) for p in sorted(RECIPES.glob("*.json"))]
    if not recipes:
        print("no recipes yet :  run distill first")
        return
    compact = []
    for r in recipes:
        compact.append({
            "title": r.get("title"),
            "hook": r.get("hook"),
            "beats": [{"beat": s.get("beat"), "purpose": s.get("purpose"),
                       "transition": s.get("transition")} for s in r.get("scenes", [])],
            "lessons": r.get("lessons", []),
        })
    content = "DISTILLED RECIPES:\n" + json.dumps(compact, indent=1)
    txt = llm.complete(STYLE_SYSTEM, [{"role": "user", "content": content}], max_tokens=1600)
    BIBLE.write_text(txt.strip() + "\n", encoding="utf-8")
    print(f"wrote {BIBLE} ({len(txt.splitlines())} lines)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "bible":
        make_bible()
    elif len(sys.argv) > 1 and sys.argv[1] == "effects":
        make_effects()
    else:
        for entry in MANIFEST:
            try:
                distill(entry)
            except Exception as e:
                print(f"  !! {entry['slug']} failed: {e}")
        if not BIBLE.exists():
            make_bible()
