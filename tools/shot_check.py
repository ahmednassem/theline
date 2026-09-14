"""Open settings -> brain -> click check keys, screenshot the verdict."""
import http.server
import threading
import time
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

UI = Path(__file__).parent.parent / "UI"
PORT = 8034
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
    page.mouse.click(*px(-A + 0.14, -0.82))  # gear
    time.sleep(2)
    page.mouse.click(*px(0.16, 0.6))  # brain tab
    time.sleep(1.5)
    page.mouse.click(*px(-0.32, -0.7))  # check keys
    time.sleep(3)
    page.screenshot(path=str(UI.parent / "data" / "capture" / "checkres.png"))
    b.close()
httpd.shutdown()
print("done")
