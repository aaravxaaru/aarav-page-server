# main.py
import os
import time
import random
import string
import json
from threading import Thread, Event
from flask import Flask, request, render_template_string

import requests

app = Flask(__name__)
app.debug = True

# store running tasks
tasks = {}

# ---------- helper ----------
def parse_cookie_string(cookie_str):
    """Convert raw cookie string into dict for requests"""
    cookies = {}
    parts = [p.strip() for p in cookie_str.split(";") if p.strip()]
    for p in parts:
        if "=" in p:
            name, val = p.split("=", 1)
            cookies[name.strip()] = val.strip()
    return cookies


def worker_send_loop(task_id, cookies_list, thread_id, prefix, interval, messages):
    """Background loop to send messages repeatedly using requests session"""
    stop_event = tasks[task_id]["stop"]

    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/114.0 Safari/537.36",
    }

    msg_index = 0
    ck_index = 0

    while not stop_event.is_set():
        try:
            cookie_dict = cookies_list[ck_index]
            msg = f"{prefix} {messages[msg_index]}".strip()

            # Example: Graph API endpoint (works only if cookies valid for mobile web send)
            url = f"https://m.facebook.com/messages/send/?icm=1&refid=12"
            data = {
                "tids": f"cid.c.{thread_id}:{thread_id}",
                "wwwupp": "C3",
                "body": msg,
                "waterfall_source": "message",
            }

            resp = session.post(url, data=data, cookies=cookie_dict, headers=headers)
            if resp.status_code == 200:
                print(f"[{task_id}] ✅ Sent: {msg}")
            else:
                print(f"[{task_id}] ❌ Failed {resp.status_code}: {resp.text[:200]}")

            msg_index = (msg_index + 1) % len(messages)
            ck_index = (ck_index + 1) % len(cookies_list)

        except Exception as e:
            print(f"[{task_id}] Error: {e}")

        # sleep with early stop check
        for _ in range(interval):
            if stop_event.is_set():
                break
            time.sleep(1)

    print(f"[{task_id}] Worker stopped.")


# ---------- Flask routes ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Messenger Bot (Render)</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
  <div class="card p-4 shadow">
    <h3 class="mb-3 text-center">Messenger Bot — Render Ready</h3>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label>Cookie File (.txt, one cookie string per line)</label>
        <input type="file" name="cookieFile" class="form-control" required>
      </div>
      <div class="mb-3">
        <label>Thread / Group ID</label>
        <input type="text" name="threadId" class="form-control" required>
      </div>
      <div class="mb-3">
        <label>Prefix (optional)</label>
        <input type="text" name="kidx" class="form-control">
      </div>
      <div class="mb-3">
        <label>Delay (seconds)</label>
        <input type="number" name="time" class="form-control" value="5" required>
      </div>
      <div class="mb-3">
        <label>Messages File (.txt)</label>
        <input type="file" name="txtFile" class="form-control" required>
      </div>
      <button class="btn btn-primary w-100">Start Task</button>
    </form>
    <hr>
    <form method="post" action="/stop">
      <label>Stop Task ID</label>
      <input type="text" name="taskId" class="form-control mb-2">
      <button class="btn btn-danger w-100">Stop</button>
    </form>
    <hr>
    <a class="btn btn-secondary w-100" href="/status">View Active Tasks</a>
  </div>
</div>
</body>
</html>
"""

@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        cookie_file = request.files.get("cookieFile")
        txt_file = request.files.get("txtFile")
        thread_id = request.form.get("threadId","").strip()
        prefix = request.form.get("kidx","").strip()
        try:
            interval = int(request.form.get("time","5"))
        except:
            interval = 5

        if not cookie_file or not txt_file or not thread_id:
            return "Missing fields",400

        cookie_lines = cookie_file.read().decode("utf-8").splitlines()
        cookies_list = [parse_cookie_string(ck) for ck in cookie_lines if ck.strip()]

        messages = [ln.strip() for ln in txt_file.read().decode("utf-8").splitlines() if ln.strip()]
        if not messages or not cookies_list:
            return "No valid cookies/messages",400

        task_id = os.urandom(4).hex()
        stop_ev = Event()
        tasks[task_id] = {"stop": stop_ev}
        t = Thread(target=worker_send_loop,args=(task_id,cookies_list,thread_id,prefix,interval,messages))
        t.daemon = False
        t.start()
        tasks[task_id]["thread"]=t
        return f"Task started with ID: {task_id}"
    return render_template_string(INDEX_HTML)

@app.route("/stop",methods=["POST"])
def stop():
    tid = request.form.get("taskId","").strip()
    if tid in tasks:
        tasks[tid]["stop"].set()
        return f"Stopping {tid}"
    return "No such task",404

@app.route("/status")
def status():
    out = {}
    for k,v in tasks.items():
        alive = v["thread"].is_alive() if "thread" in v else False
        out[k]={"alive":alive}
    return out

if __name__=="__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port)
