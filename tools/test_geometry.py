"""Unit tests for the free geometry gate (server/geometry.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from server import geometry  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""))
    if not cond:
        FAILS.append(name)


# 1. clean scene passes untouched
res = geometry.check_and_fix([
    {"op": "axes", "x": [0, 6.28], "y": [-1.4, 1.4]},
    {"op": "plot", "fn": "sin(x)", "domain": [0, 6.28], "id": "sine"},
    {"op": "write", "text": "y = sin(x)", "at": [0.9, 0.8], "size": 0.09, "id": "lbl"},
])
check("clean scene ok", res["ok"] and not res["fixes"], str(res["reasons"] + res["fixes"]))

# 2. label on top of the curve gets relocated (auto-fix, still ok)
res = geometry.check_and_fix([
    {"op": "axes", "x": [0, 6.28], "y": [-1.4, 1.4]},
    {"op": "plot", "fn": "sin(x)", "domain": [0, 6.28], "id": "sine"},
    {"op": "write", "text": "y = sin(x)", "at": [-0.57, 0.5], "size": 0.09, "id": "lbl"},
])
moved = next(o for o in res["ops"] if o["op"] == "write")
check("overlapping label relocated", res["ok"] and moved["at"] != [-0.57, 0.5],
      f"moved to {moved['at']}, fixes={res['fixes']}")

# 3. two labels colliding -> second one moves
res = geometry.check_and_fix([
    {"op": "write", "text": "hello", "at": [0, 0], "size": 0.1, "id": "a"},
    {"op": "write", "text": "world", "at": [0.05, 0.02], "size": 0.1, "id": "b"},
])
b = [o for o in res["ops"] if o.get("id") == "b"][0]
check("text-text collision fixed", res["ok"] and b["at"] != [0.05, 0.02], f"b at {b['at']}")

# 4. off-screen label clamped back in
res = geometry.check_and_fix([
    {"op": "write", "text": "far away", "at": [2.5, 0.0], "size": 0.09, "id": "far"},
])
far = res["ops"][0]
check("off-screen label clamped", res["ok"] and far["at"][0] < 1.6, f"at {far['at']}")

# 5. bad function -> precise reason, no crash
res = geometry.check_and_fix([
    {"op": "plot", "fn": "sin(x) + import os", "domain": [0, 5], "id": "evil"},
])
check("evil fn rejected", not res["ok"] and "rejected" in res["reasons"][0], res["reasons"][0][:60])

# 6. fn invalid everywhere -> reason
res = geometry.check_and_fix([
    {"op": "axes", "x": [-5, -1], "y": [-2, 2]},
    {"op": "plot", "fn": "sqrt(x)", "domain": [-5, -1], "id": "imag"},
])
check("nan-everywhere fn rejected", not res["ok"], str(res["reasons"])[:70])

# 7. off-screen circle -> reason (plot coords far outside)
res = geometry.check_and_fix([
    {"op": "axes", "x": [0, 6.28], "y": [-1.4, 1.4]},
    {"op": "circle", "at": [20, 0], "r": 0.1, "id": "lost"},
])
check("off-screen circle reported", not res["ok"] and "leaves the screen" in res["reasons"][0],
      res["reasons"][0][:70])

# 8. emphasize of unknown id silently dropped
res = geometry.check_and_fix([
    {"op": "write", "text": "hi", "at": [0, 0.8], "id": "t"},
    {"op": "emphasize", "id": "ghost"},
])
check("unknown emphasize dropped", res["ok"] and all(o["op"] != "emphasize" for o in res["ops"]),
      str(res["fixes"]))

# 9. circle marker ON a curve is allowed (shapes may touch curves)
res = geometry.check_and_fix([
    {"op": "axes", "x": [0, 6.28], "y": [-1.4, 1.4]},
    {"op": "plot", "fn": "sin(x)", "domain": [0, 6.28], "id": "sine"},
    {"op": "circle", "at": [1.57, 1], "r": 0.06, "id": "peak"},
])
check("on-curve marker allowed", res["ok"], str(res["reasons"]))

# 10. expression evaluator sanity
f = geometry.compile_expr("sin(pi/2) + x^2")
check("expr eval", abs(f(3) - 10.0) < 1e-9, f"f(3)={f(3)}")

# ---------------------------------------------------------------- v2.2
# 11. cross-scene collision: scene 2 text over scene 1 text -> rejected with replace hint
r1 = geometry.check_and_fix([
    {"op": "write", "text": "C / d = 3.14...", "slot": "formula_band", "id": "formula_ratio"},
], scene_no=1)
check("scene 1 slot write ok", r1["ok"], str(r1["reasons"]))
r2 = geometry.check_and_fix([
    {"op": "write", "text": "pi = 3.14159", "at": [0, -0.55], "id": "pi_val"},
], registry=r1["registry"], scene_no=2)
check("cross-scene overlap rejected", not r2["ok"] and "replace" in r2["reasons"][0],
      r2["reasons"][0][:80])

# 12. replace fixes it: old fades, new takes the slot
r3 = geometry.check_and_fix([
    {"op": "replace", "old": "formula_ratio",
     "with": {"op": "write", "text": "pi = 3.14159", "id": "pi_val"}},
], registry=r1["registry"], scene_no=2)
kinds = [o["op"] for o in r3["ops"]]
new_el = r3["registry"]["elements"]
check("replace -> fade + write", r3["ok"] and kinds == ["fade", "write"], str(kinds))
check("registry updated by replace",
      len(new_el) == 1 and new_el[0]["id"] == "pi_val" and new_el[0]["slot"] == "formula_band",
      str([(e['id'], e.get('slot')) for e in new_el]))

# 13. occupied slot in the same scene -> rejected
r4 = geometry.check_and_fix([
    {"op": "write", "text": "one", "slot": "title_band", "id": "a"},
    {"op": "write", "text": "two", "slot": "title_band", "id": "b"},
], scene_no=1)
check("occupied slot rejected", not r4["ok"] and "occupied" in r4["reasons"][0], r4["reasons"][0][:70])

# 14. arrow path through an unrelated label -> rejected
r5 = geometry.check_and_fix([
    {"op": "write", "text": "blocker", "at": [0, 0], "size": 0.1, "id": "blk"},
    {"op": "arrow", "from": [-1.0, 0.0], "to": [1.0, 0.0], "id": "arr"},
], scene_no=1)
check("arrow through label rejected", not r5["ok"] and "crosses" in r5["reasons"][0],
      r5["reasons"][0][:80])

# 15. symbol gate: pi shown before its introducing scene -> rejected
r6 = geometry.check_and_fix([
    {"op": "write", "text": "pi = 3.14", "slot": "formula_band", "id": "early"},
], scene_no=1, future_symbols={"pi": 4})
check("early symbol rejected", not r6["ok"] and "scene 4" in r6["reasons"][0], r6["reasons"][0][:80])

# 16. effect anti-repeat is a soft reason
r7a = geometry.check_and_fix([
    {"op": "arrow", "from": [-1.0, 0.5], "to": [1.0, 0.5], "id": "a1"},
], scene_no=1)
r7b = geometry.check_and_fix([
    {"op": "arrow", "from": [-1.0, -0.5], "to": [1.0, -0.5], "id": "a2"},
], registry=r7a["registry"], scene_no=2)
check("effect repeat soft-flagged", r7b["ok"] and len(r7b["soft"]) == 1, str(r7b["soft"])[:80])

# 17. clear empties the registry
r8 = geometry.check_and_fix([{"op": "clear"}], registry=r1["registry"], scene_no=2)
check("clear empties registry", r8["ok"] and not r8["registry"]["elements"], "")

# ---------------------------------------------------------------- blind-spot fixes
# 18. THE SCREENSHOT BUG: two unnamed writes at the same spot must be
# collision-handled, not silently merged under one registry id
r9 = geometry.check_and_fix([
    {"op": "write", "text": "3.14159265...", "at": [0, 0.2], "size": 0.12},
    {"op": "write", "text": "pi =", "at": [-0.45, 0.22], "size": 0.1},
], scene_no=1)
w9 = [o for o in r9["ops"] if o["op"] == "write"]
check("unnamed writes: both tracked", len(r9["registry"]["elements"]) == 2,
      f"{len(r9['registry']['elements'])} elements")
check("unnamed writes: overlap handled",
      r9["ok"] and w9[1]["at"] != [-0.45, 0.22] and len(r9["fixes"]) >= 1,
      f"second at {w9[1]['at']}, fixes={r9['fixes']}")

# 19. ids injected, unique, and persisted across scenes
check("ids injected + unique", w9[0]["id"] != w9[1]["id"] and w9[0]["id"] and w9[1]["id"],
      f"{w9[0]['id']} / {w9[1]['id']}")
r10 = geometry.check_and_fix([
    {"op": "circle", "at": [0.5, -0.5], "r": 0.1},
], registry=r9["registry"], scene_no=2)
new_ids = {e["id"] for e in r10["registry"]["elements"]}
check("cross-scene id uniqueness", len(new_ids) == 3, str(new_ids))

# 20. aspect-aware bounds: x=1.9 text fits a 2.2 window, not a 1.3 window
wide = geometry.check_and_fix([{"op": "write", "text": "edge", "at": [1.9, 0], "size": 0.08}],
                              scene_no=1, aspect=2.2)
narrow = geometry.check_and_fix([{"op": "write", "text": "edge", "at": [1.9, 0], "size": 0.08}],
                                scene_no=1, aspect=1.3)
w_at = wide["ops"][0]["at"][0]
n_at = narrow["ops"][0]["at"][0]
check("wide window keeps x=1.9", wide["ok"] and abs(w_at - 1.9) < 0.05, f"at {w_at}")
check("narrow window pulls it in", narrow["ok"] and n_at < 1.25, f"at {n_at}")

print()
if FAILS:
    print("FAILED:", FAILS)
    sys.exit(1)
print("all geometry tests passed")
