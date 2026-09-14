"""End-to-end test of /api/ask (pipeline v2): quick mode + video mode."""
import json
import sys
import time
import urllib.request

# narration may contain non-ascii (e.g. a real pi character) :  don't die on cp1252 consoles
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ask(messages, mode):
    r = urllib.request.Request(
        "http://127.0.0.1:8002/api/ask",
        data=json.dumps({"messages": messages, "mode": mode}).encode(),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    lines = []
    with urllib.request.urlopen(r, timeout=600) as resp:
        for line in resp:
            seg = json.loads(line)
            lines.append(line.decode().strip())
            meta = seg.get("meta", {})
            tag = f"scene {meta.get('scene')}/{meta.get('of')}"
            if meta.get("flagged"):
                tag += " FLAGGED"
            if meta.get("filler"):
                tag += " FILLER"
            print(f"[{time.time()-t0:5.1f}s] {tag}: {seg['narration'][:75]}")
            for op in seg.get("ops", []):
                print("          op:", json.dumps(op)[:105])
    return lines


mode = sys.argv[1] if len(sys.argv) > 1 else "quick"
q = sys.argv[2] if len(sys.argv) > 2 else (
    "what is pi?" if mode == "quick" else "explain how sine relates to circles"
)
print(f"--- mode={mode}: {q}")
ask([{"role": "user", "content": q}], mode)
