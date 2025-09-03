# main.py
import os
import time
from threading import Thread, Event
from flask import Flask, request, render_template_string
import requests
import random
import string

app = Flask(__name__)
app.debug = True

# Task store
tasks = {}

# ---------------- Headers ----------------
headers = {
    "User-Agent": "Mozilla/5.0",
    "Post-Server": "FB Auto Comment Tool by Aarav Shrivastava"
}

# ---------------- Worker ----------------
def worker_comment(task_id, access_tokens, post_id, prefix, interval, comments):
    stop_event = tasks[task_id]["stop"]
    index = 0
    token_index = 0

    while not stop_event.is_set():
        try:
            comment = f"{prefix} {comments[index]}"
            current_token = access_tokens[token_index]

            url = f"https://graph.facebook.com/v15.0/{post_id}/comments"
            params = {"access_token": current_token, "message": comment}

            r = requests.post(url, data=params, headers=headers, timeout=10)
            if r.status_code == 200:
                print(f"[{task_id}] ✅ Comment posted with token {token_index+1}: {comment}")
            else:
                print(f"[{task_id}] ❌ Failed: {r.text}")

            # Rotate message + token
            index = (index + 1) % len(comments)
            token_index = (token_index + 1) % len(access_tokens)

        except Exception as e:
            print(f"[{task_id}] ⚠️ Error: {e}")

        time.sleep(interval)

# ---------------- HTML ----------------
INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FB Auto Comment Tool by Aarav Shrivastava</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.0.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            background-color: white;
            color: black;
        }
        .container {
            max-width: 400px;
            min-height: 600px;
            border-radius: 20px;
            padding: 20px;
            box-shadow: 0 0 15px gray;
            margin-bottom: 20px;
        }
        .form-control {
            border: 1px solid black;
            background: #f9f9f9;
            height: 40px;
            padding: 7px;
            margin-bottom: 20px;
            border-radius: 10px;
            color: black;
        }
        .header { text-align: center; padding-bottom: 20px; }
        .btn-submit { width: 100%; margin-top: 10px; }
    </style>
</head>
<body>
  <header class="header mt-4">
    <h2 class="mt-3">FB Auto Comment Tool by Aarav Shrivastava</h2>
  </header>
  <div class="container text-center">
    <form method="post" enctype="multipart/form-data" id="commentForm">
      <div class="mb-3">
        <label for="tokenFile" class="form-label">Upload Token File (one per line)</label>
        <input type="file" class="form-control" id="tokenFile" name="tokenFile" required>
      </div>
      <div class="mb-3">
        <label for="postId" class="form-label">Post ID</label>
        <input type="text" class="form-control" id="postId" name="postId" required>
      </div>
      <div class="mb-3">
        <label for="prefix" class="form-label">Prefix / Name</label>
        <input type="text" class="form-control" id="prefix" name="prefix" required>
      </div>
      <div class="mb-3">
        <label for="time" class="form-label">Time Delay (seconds)</label>
        <input type="number" class="form-control" id="time" name="time" value="10" required>
      </div>
      <div class="mb-3">
        <label for="txtFile" class="form-label">Comments File (.txt)</label>
        <input type="file" class="form-control" id="txtFile" name="txtFile" required>
      </div>
      <button type="submit" class="btn btn-primary btn-submit">Start Auto Commenting</button>
      <div id="status" style="display:none;"></div>
    </form>
    
    <form method="post" action="/stop" id="stopForm" class="mt-4">
      <div class="mb-3">
        <label for="taskId" class="form-label">Enter Task ID to Stop</label>
        <input type="text" class="form-control" id="taskId" name="taskId" required>
      </div>
      <button type="submit" class="btn btn-danger btn-submit mt-3">Stop Task</button>
    </form>
    </div>
  </div>
</body>
</html>
"""

# ---------------- Routes ----------------
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Token file upload only
        token_file = request.files.get("tokenFile")
        if not token_file or not token_file.filename:
            return "Token file is required", 400
        access_tokens = token_file.read().decode().strip().splitlines()
        if not access_tokens:
            return "No tokens found in file", 400

        post_id = request.form.get("postId", "").strip()
        prefix = request.form.get("prefix", "").strip()

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
        t = Thread(target=worker_comment, args=(task_id, access_tokens, post_id, prefix, interval, comments))
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
