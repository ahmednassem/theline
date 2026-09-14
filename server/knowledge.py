"""The learned 3b1b craft: style bible + per-video recipes.

Distilled offline by tools/learn_3b1b.py from Grant's actual published
Manim source and transcripts. Loaded once here; the pipeline injects the
bible into every prompt and 1-2 matched recipes into the planner.
Degrades to empty strings when knowledge/ doesn't exist.
"""
import json
import re
from pathlib import Path

KNOWLEDGE = Path(__file__).parent.parent / "knowledge"

_STOP = {"the", "and", "for", "what", "how", "why", "is", "are", "a", "an", "of",
         "to", "in", "on", "me", "my", "it", "that", "this", "explain", "show",
         "about", "does", "do", "can", "you", "tell", "at", "by", "or", "so",
         "up", "we", "he", "us", "be", "as", "if", "no", "am", "its"}


def _load():
    bible = ""
    recipes = []
    effects_list = []
    try:
        f = KNOWLEDGE / "style_bible.md"
        if f.exists():
            bible = f.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        pass
    try:
        for p in sorted((KNOWLEDGE / "recipes").glob("*.json")):
            try:
                r = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                if r.get("scenes"):
                    recipes.append(r)
            except Exception:
                pass
    except Exception:
        pass
    try:
        f = KNOWLEDGE / "effects.json"
        if f.exists():
            effects_list = [e for e in json.loads(f.read_text(encoding="utf-8", errors="replace"))
                            if isinstance(e, dict) and e.get("name") and e.get("how")]
    except Exception:
        pass
    return bible, recipes, effects_list


_BIBLE, _RECIPES, _EFFECTS = _load()


def bible():
    return _BIBLE


def effects():
    """Visual effects palette distilled from 3b1b's transitions."""
    return _EFFECTS


def _tokens(text):
    # "pi" and "e" are the most important short words in math :  keep them
    return {w for w in re.findall(r"[a-z]+", text.lower())
            if (len(w) > 1 or w == "e") and w not in _STOP}


def match(question, k=2):
    """Recipes whose tags/title overlap the question, best first."""
    q = _tokens(question)
    scored = []
    for r in _RECIPES:
        vocab = _tokens(r.get("tags", "") + " " + r.get("title", ""))
        score = len(q & vocab)
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda t: -t[0])
    return [r for _, r in scored[:k]]


def _render(r, budget):
    lines = [f"* \"{r.get('title', r.get('slug', ''))}\"", f"  hook: {r.get('hook', '')}"]
    for i, s in enumerate(r.get("scenes", []), 1):
        on = ", ".join(f"{o.get('kind')}@{o.get('zone')}" for o in (s.get("on_screen") or [])[:4])
        lines.append(f"  {i}. [{s.get('beat')}] {s.get('purpose', '')} :  shows: {on} :  transition: {s.get('transition', '')}")
    for les in r.get("lessons", [])[:4]:
        lines.append(f"  rule: {les}")
    out = "\n".join(lines)
    return out[:budget]


def exemplar_block(question, k=2, budget=2500):
    """Compact worked examples for the planner, or "" when nothing matches."""
    hits = match(question, k)
    if not hits:
        return ""
    per = budget // len(hits)
    body = "\n".join(_render(r, per) for r in hits)
    return ("HOW 3B1B STAGED SIMILAR TOPICS (mirror the staging discipline, "
            "not the content):\n" + body)
