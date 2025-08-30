# main.py (cookies from file)
import os, time, random
from threading import Thread, Event
from flask import Flask, request, render_template_string
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager

app = Flask(__name__)
tasks = {}

def parse_cookie_string(cookie_str):
    cookies = []
    for part in cookie_str.split(";"):
        if "=" in part:
            name, val = part.strip().split("=", 1)
            cookies.append({"name": name, "value": val, "domain": ".facebook.com", "path": "/"})
    return cookies

def make_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1200,900")
    return webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)

def send_with_cookie(cookie_str, thread_id, message, headless=True):
    driver = make_driver(headless)
    try:
        driver.get("https://mbasic.facebook.com/")
        time.sleep(1)
        for c in parse_cookie_string(cookie_str):
            try: driver.add_cookie(c)
            except: pass
        driver.get(f"https://mbasic.facebook.com/messages/thread/{thread_id}")
        time.sleep(2)
        try:
            box = driver.find_element(By.NAME, "body")
            box.clear()
            box.send_keys(message)
            btn = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Send']")
            btn.click()
            return True
        except Exception as e:
            print("Send error:", e)
            return False
    finally:
        driver.quit()

def worker(task_id, cookie_list, thread_id, prefix, interval, messages, headless):
    stop_ev = tasks[task_id]["stop"]
    msg_index = 0
    ck_index = 0
    while not stop_ev.is_set():
        msg = f"{prefix} {messages[msg_index]}".strip()
        cookie = cookie_list[ck_index]
        ok = send_with_cookie(cookie, thread_id, msg, headless)
        print(f"[{task_id}] Cookie#{ck_index} → {msg} → {'OK' if ok else 'FAIL'}")
        msg_index = (msg_index + 1) % len(messages)
        ck_index = (ck_index + 1) % len(cookie_list)
        for _ in range(interval):
            if stop_ev.is_set(): break
            time.sleep(1)

# -------- Flask Routes --------
HTML = """
<h2>Messenger Bot (Multi-Cookie)</h2>
<form method="post" enctype="multipart/form-data">
  <label>Cookies File (.txt, each line one cookie string)</label><br>
  <input type="file" name="cookieFile" required><br><br>
  <label>Thread ID:</label><br>
  <input name="threadId" required><br><br>
  <label>Prefix:</label><br>
  <input name="prefix"><br><br>
  <label>Interval (sec):</label><br>
  <input type="number" name="time" value="10"><br><br>
  <label>Messages File (.txt)</label><br>
  <input type="file" name="txtFile" required><br><br>
  <input type="checkbox" name="headless" checked> Headless<br><br>
  <button>Start</button>
</form>
<hr>
<form method="post" action="/stop">
  <label>Task ID to Stop:</label>
  <input name="taskId"><button>Stop</button>
</form>
<a href="/status">Status</a>
"""

@app.route("/", methods=["GET","POST"])
def index():
    if request.method=="POST":
        cookie_file = request.files.get("cookieFile")
        txt_file = request.files.get("txtFile")
        if not cookie_file or not txt_file:
            return "Files missing",400
        cookie_list = [ln.strip() for ln in cookie_file.read().decode().splitlines() if ln.strip()]
        messages = [ln.strip() for ln in txt_file.read().decode().splitlines() if ln.strip()]
        thread_id = request.form.get("threadId")
        prefix = request.form.get("prefix","")
        interval = int(request.form.get("time","10"))
        headless = True if request.form.get("headless") else False

        tid = os.urandom(4).hex()
        stop_ev = Event()
        tasks[tid] = {"stop": stop_ev}
        t = Thread(target=worker, args=(tid, cookie_list, thread_id, prefix, interval, messages, headless))
        tasks[tid]["thread"]=t
        t.start()
        return f"Started task {tid}"
    return render_template_string(HTML)

@app.route("/stop", methods=["POST"])
def stop():
    tid=request.form.get("taskId")
    if tid in tasks:
        tasks[tid]["stop"].set()
        return f"Stopping {tid}"
    return "Not found",404

@app.route("/status")
def status():
    return {k: v["thread"].is_alive() for k,v in tasks.items()}
