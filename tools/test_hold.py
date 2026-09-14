"""Stage error note + list hold/resume test."""
import http.server
import threading
import time
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

UI = Path(__file__).parent.parent / "UI"
OUT = UI.parent / "data" / "capture"
PORT = 8044
W, H = 1280, 720
A = W / H


def px(x, y):
    return int((x / A + 1) / 2 * W), int((1 - y) / 2 * H)


handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(UI))
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": W, "height": H})
    page.goto(f"http://127.0.0.1:{PORT}/")
    page.wait_for_function("() => !!(window.__line && window.__line.playDemo)")
    time.sleep(2)
    page.keyboard.type("random nonsense question xyz")
    page.keyboard.press("Enter")
    time.sleep(2.5)
    page.screenshot(path=str(OUT / "n_error.png"))
    page.keyboard.press("Escape")
    time.sleep(1)
    page.evaluate("window.__line.playDemo('quick-math')")
    time.sleep(7)
    page.mouse.click(*px(-A + 0.3, -0.82))  # open list mid-demo
    time.sleep(2)
    page.screenshot(path=str(OUT / "n_hold.png"))
    page.mouse.click(*px(-A + 0.3, -0.82))  # close list -> resume
    time.sleep(5)
    page.screenshot(path=str(OUT / "n_resumed.png"))
    b.close()
httpd.shutdown()
print("done")
