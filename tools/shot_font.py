"""Screenshots of list, settings, and a scene with the current font."""
import http.server
import threading
import time
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

UI = Path(__file__).parent.parent / "UI"
OUT = UI.parent / "data" / "capture"
PORT = 8033
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
    # demo list
    page.mouse.click(*px(-A + 0.3, -0.82))
    time.sleep(2)
    page.screenshot(path=str(OUT / "f_list.png"))
    page.keyboard.press("Escape")
    time.sleep(1)
    # settings (gear at bottom-left), then brain tab
    page.mouse.click(*px(-A + 0.14, -0.82))
    time.sleep(2)
    page.mouse.click(*px(0.16, 0.6))
    time.sleep(2)
    page.screenshot(path=str(OUT / "f_settings.png"))
    page.keyboard.press("Escape")
    time.sleep(1.5)
    # a scene mid-write
    page.evaluate("window.__line.playDemo('quick-math')")
    time.sleep(7)
    page.screenshot(path=str(OUT / "f_scene.png"))
    b.close()
httpd.shutdown()
print("shots done")
