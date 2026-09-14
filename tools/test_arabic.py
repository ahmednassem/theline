"""Quick check: question in Arabic -> narration must be English."""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
q = "\u0645\u0627 \u0647\u064a \u0627\u0644\u062c\u0627\u0630\u0628\u064a\u0629\u061f"  # "what is gravity?"
print("question:", q)
r = urllib.request.Request(
    "http://127.0.0.1:8002/api/ask",
    data=json.dumps({"messages": [{"role": "user", "content": q}], "mode": "auto"}).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(r, timeout=600) as resp:
    for line in resp:
        seg = json.loads(line)
        print(f"scene {seg['meta']['scene']}/{seg['meta']['of']}: {seg['narration'][:90]}")
