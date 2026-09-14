"""Click the demo-list icon mid-playback: the show must stop and the list open."""
import http.server
import threading
import time
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

UI = Path(__file__).parent.parent / "UI"
PORT = 8032


def px(x, y, w=1280, h=720):
    a = w / h / 1  # aspect used by the app = width/height
    return int((x / (w / h) + 1) / 2 * w), int((1 - y) / 2 * h)


handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(UI))
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page(viewport={"width": 1280, "height": 720})
    page.goto(f"http://127.0.0.1:{PORT}/")
    page.wait_for_function("() => !!(window.__line && window.__line.playDemo)")
    time.sleep(2)
    page.evaluate("window.__line.playDemo('quick-math')")
    time.sleep(6)  # well into scene 1
    page.screenshot(path=str(UI.parent / "data" / "capture" / "t1_playing.png"))
    ix, iy = px(-1280 / 720 + 0.3, -0.82)
    page.mouse.click(ix, iy)  # the list icon, mid-demo
    time.sleep(2.5)
    page.screenshot(path=str(UI.parent / "data" / "capture" / "t2_after_click.png"))
    done = page.evaluate("window.__lineDone")
    print("lineDone after click:", done)
    b.close()
httpd.shutdown()
