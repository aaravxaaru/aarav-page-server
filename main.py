# main.py
import os
import time
import random
import string
import json
from threading import Thread, Event
from flask import Flask, request, render_template_string, redirect, url_for
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)
app.debug = True

# store tasks: task_id -> {"thread": Thread, "stop": Event, "driver": webdriver or None}
tasks = {}

# ---------- helper functions ----------
def parse_cookie_string(cookie_str):
    """
    Parse cookie string like "a=1; b=2" -> list of dicts for selenium
    """
    cookies = []
    parts = [p.strip() for p in cookie_str.split(";") if p.strip()]
    for p in parts:
        if "=" in p:
            name, val = p.split("=", 1)
            cookies.append({"name": name.strip(), "value": val.strip(), "domain": ".facebook.com", "path": "/"})
    return cookies

def make_driver(headless=True):
    """
    Create a Chrome webdriver using webdriver-manager (auto-download chromedriver).
    Set some common flags to work in headless servers.
    """
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless=new")  # newer headless
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1200,900")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    # optional: reduce detection surface
    chrome_options.add_experimental_option("excludeSwitches", ["enable-logging","enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    # optional: try to avoid detection flags
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
            """
        })
    except Exception:
        pass
    return driver

def find_message_input_and_send(driver, message, max_wait=10):
    """
    Tries multiple strategies to find message input and send message on mobile/desktop view.
    Returns True if send seems successful, False otherwise.
    """
    wait = WebDriverWait(driver, max_wait)
    # Try known selectors in order (mobile m.facebook & mbasic)
    try:
        # strategy 1: mobile messenger composer textarea or contenteditable
        # m.facebook: contenteditable div with role="textbox"
        elm = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[contenteditable="true"][role="textbox"]')))
        elm.click()
        elm.clear()
        elm.send_keys(message)
        elm.send_keys(Keys.ENTER)
        return True
    except Exception:
        pass

    try:
        # strategy 2: mbasic composer textarea name="body"
        elm = driver.find_element(By.NAME, "body")
        elm.clear()
        elm.send_keys(message)
        # find send button (input type=submit with value Send)
        try:
            btn = driver.find_element(By.XPATH, "//input[@type='submit' and (translate(@value,'SENDsend','send')='send' or contains(translate(@value,'send','SEND'),'send'))]")
            btn.click()
        except Exception:
            elm.send_keys(Keys.ENTER)
        return True
    except Exception:
        pass

    try:
        # strategy 3: message box by aria-label (desktop)
        elm = driver.find_element(By.CSS_SELECTOR, 'div[aria-label="Message"]')
        elm.click()
        elm.send_keys(message)
        elm.send_keys(Keys.ENTER)
        return True
    except Exception:
        pass

    # strategy 4: generic textarea
    try:
        elm = driver.find_element(By.TAG_NAME, "textarea")
        elm.clear()
        elm.send_keys(message)
        elm.send_keys(Keys.ENTER)
        return True
    except Exception:
        pass

    return False

# ---------- send thread ----------
def worker_send_loop(task_id, cookie_str, thread_id, prefix, interval, messages, headless):
    """
    Background thread: launches browser, injects cookies, navigates to thread, and sends messages repeatedly.
    """
    stop_event = tasks[task_id]["stop"]
    driver = None
    try:
        driver = make_driver(headless=headless)
        tasks[task_id]["driver"] = driver

        # Step 1: visit facebook main domain to set cookies
        driver.get("https://m.facebook.com/")  # mobile site works well
        time.sleep(1)

        # Inject cookies
        cookie_list = parse_cookie_string(cookie_str)
        for c in cookie_list:
            # selenium requires domain matching current url; use domain .facebook.com
            try:
                driver.add_cookie({"name": c["name"], "value": c["value"], "domain": c.get("domain", ".facebook.com"), "path": "/"})
            except Exception:
                # if add_cookie fails, attempt without domain
                try:
                    driver.add_cookie({"name": c["name"], "value": c["value"], "path": "/"})
                except Exception:
                    pass

        # Refresh so cookies take effect and session logs in
        driver.get("https://m.facebook.com/")
        time.sleep(2)

        # Basic check: is logged in? look for profile link or c_user presence in cookies
        logged_in = any([c['name'] == 'c_user' for c in driver.get_cookies()])
        if not logged_in:
            print(f"[{task_id}] Warning: c_user cookie not present or login not successful. Continue anyway.")

        # navigate to the conversation thread
        # thread URL formats:
        # m.facebook.com/messages/t/<thread_id>
        # mbasic.facebook.com/messages/thread/<thread_id>
        thread_url_candidates = [
            f"https://m.facebook.com/messages/t/{thread_id}",
            f"https://mbasic.facebook.com/messages/thread/{thread_id}",
            f"https://m.facebook.com/messages/read/?tid={thread_id}"
        ]

        # Try each candidate
        success_nav = False
        for url in thread_url_candidates:
            try:
                driver.get(url)
                time.sleep(2)
                # if page loaded and contains some message area, proceed
                if "messages" in driver.current_url or "thread" in driver.current_url or driver.title:
                    success_nav = True
                    break
            except Exception:
                continue

        if not success_nav:
            print(f"[{task_id}] Could not navigate to thread URL. Current URL: {driver.current_url}")

        msg_index = 0
        # send loop
        while not stop_event.is_set():
            try:
                message_text = f"{prefix} {messages[msg_index]}".strip()
                ok = find_message_input_and_send(driver, message_text, max_wait=8)
                if ok:
                    print(f"[{task_id}] Sent message: {message_text}")
                else:
                    print(f"[{task_id}] Could not find message input to send: {message_text}")
                msg_index = (msg_index + 1) % len(messages)
            except Exception as e:
                print(f"[{task_id}] Error during send: {e}")
            # wait interval but allow quick stop
            for _ in range(int(max(1, interval))):
                if stop_event.is_set():
                    break
                time.sleep(1)
    except Exception as e:
        print(f"[{task_id}] Fatal worker error: {e}")
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        tasks[task_id]["driver"] = None
        print(f"[{task_id}] Worker exited.")

# ---------- Flask routes ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Messenger Selenium Bot</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: linear-gradient(135deg,#0f172a,#0ea5e9); color:#e6eef8; font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; }
    .card { border-radius: 14px; box-shadow: 0 10px 30px rgba(2,6,23,0.6); background: linear-gradient(180deg,#ffffff,#f7fbff); color:#042a48; }
    label { font-weight:600; color:#0b2540; }
    textarea.form-control { height:120px; resize:vertical; }
    .muted { color:#5b6b76; font-size:0.9rem; }
    .small { font-size:0.85rem; }
    .top-note { font-size:0.9rem; color:#073b4c; }
    .task-box { background:#0b1220; color:#cde7ff; padding:10px; border-radius:8px; }
  </style>
</head>
<body>
  <div class="container py-5">
    <div class="row justify-content-center">
      <div class="col-md-8 col-lg-6">
        <div class="card p-4">
          <h3 class="text-center mb-3">Messenger Bot — Selenium</h3>
          <p class="top-note text-center">Use only for testing with accounts you own. Read the warnings in the app logs.</p>

          <form method="post" enctype="multipart/form-data">
            <div class="mb-3">
              <label>Facebook Cookie (paste full cookie string)</label>
              <textarea name="cookie" class="form-control" placeholder="c_user=...; xs=...; ..." required></textarea>
              <div class="small muted mt-1">Tip: paste the cookie string from browser devtools → Application → Cookies</div>
            </div>

            <div class="mb-3">
              <label>Thread / Group ID</label>
              <input type="text" name="threadId" class="form-control" placeholder="e.g. 1234567890" required>
            </div>

            <div class="mb-3">
              <label>Prefix (optional)</label>
              <input type="text" name="kidx" class="form-control" placeholder="[Bot]">
            </div>

            <div class="mb-3">
              <label>Time Delay (seconds)</label>
              <input type="number" name="time" class="form-control" value="8" min="1">
            </div>

            <div class="mb-3">
              <label>Messages File (.txt)</label>
              <input type="file" name="txtFile" class="form-control" required>
              <div class="small muted mt-1">One message per line</div>
            </div>

            <div class="mb-3 form-check">
              <input class="form-check-input" type="checkbox" id="headless" name="headless" checked>
              <label class="form-check-label small" for="headless">Run headless (no browser window). Uncheck for visual debugging.</label>
            </div>

            <button class="btn btn-primary w-100 mb-2">Start Task</button>
          </form>

          <hr>

          <div class="mb-3">
            <form method="post" action="/stop">
              <label>Stop Task ID</label>
              <input type="text" name="taskId" class="form-control" placeholder="Enter task id">
              <button class="btn btn-danger mt-2 w-100">Stop</button>
            </form>
          </div>

          <div class="mb-2">
            <a class="btn btn-outline-secondary w-100" href="/status">View Active Tasks</a>
          </div>

          <div class="mt-3 small muted">
            <strong>Important:</strong> Use test accounts and low send rates. This bot automates a real browser — misuse risks account penalties.
          </div>
        </div>

        <div class="task-box mt-3">
          <div><strong>Last logs:</strong></div>
          <pre id="logs" style="max-height:180px; overflow:auto;">Check console logs where server runs.</pre>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        cookie = request.form.get("cookie", "").strip()
        thread_id = request.form.get("threadId", "").strip()
        prefix = request.form.get("kidx", "").strip()
        try:
            interval = int(request.form.get("time", "8"))
            interval = max(1, interval)
        except Exception:
            interval = 8
        headless = True if request.form.get("headless") else False

        f = request.files.get("txtFile")
        if not f:
            return "Messages file required", 400
        try:
            messages = [ln.strip() for ln in f.read().decode("utf-8", errors="ignore").splitlines() if ln.strip()]
            if not messages:
                return "Message file empty", 400
        except Exception as e:
            return f"Failed to read messages file: {e}", 400

        # create task
        task_id = os.urandom(4).hex()
        stop_ev = Event()
        tasks[task_id] = {"thread": None, "stop": stop_ev, "driver": None}
        t = Thread(target=worker_send_loop, args=(task_id, cookie, thread_id, prefix, interval, messages, headless))
        tasks[task_id]["thread"] = t
        t.daemon = False
        t.start()
        return f"Task started. ID: {task_id}"

    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
def stop_task():
    tid = request.form.get("taskId", "").strip()
    if not tid:
        return "taskId required", 400
    info = tasks.get(tid)
    if not info:
        return "No such task", 404
    info["stop"].set()
    # quit driver if present
    drv = info.get("driver")
    if drv:
        try:
            drv.quit()
        except Exception:
            pass
    return f"Stopping task {tid}"

@app.route("/status")
def status():
    out = {}
    for k, v in tasks.items():
        alive = v["thread"].is_alive() if v["thread"] else False
        out[k] = {"alive": alive}
    return out

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
