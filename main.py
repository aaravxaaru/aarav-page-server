from flask import Flask, request, render_template_string
import requests, re, time, random, string, os
from threading import Thread, Event

app = Flask(__name__)
stop_events = {}
threads = {}

def parse_cookie(cookie_str):
    cookies = {}
    for part in cookie_str.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            cookies[key] = value
    return cookies

def get_form_data(session, thread_id):
    url = f"https://mbasic.facebook.com/messages/thread/{thread_id}"
    r = session.get(url, timeout=10)
    if r.status_code != 200:
        raise Exception("Failed to load thread page")

    fb_dtsg = re.search(r'name="fb_dtsg" value="(.*?)"', r.text).group(1)
    jazoest = re.search(r'name="jazoest" value="(.*?)"', r.text).group(1)
    return fb_dtsg, jazoest

def send_messages(cookie_str, thread_id, prefix, time_interval, messages, task_id):
    stop_event = stop_events[task_id]
    cookies = parse_cookie(cookie_str)
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    })

    msg_index = 0
    while not stop_event.is_set():
        try:
            fb_dtsg, jazoest = get_form_data(session, thread_id)
            message = f"{prefix} {messages[msg_index]}"

            url = "https://mbasic.facebook.com/messages/send/"
            data = {
                "fb_dtsg": fb_dtsg,
                "jazoest": jazoest,
                "body": message,
                "tids": f"cid.g.{thread_id}",
                "send": "Send"
            }

            resp = session.post(url, data=data, timeout=10)
            if "send" in resp.url or resp.status_code == 200:
                print(f"✅ Sent: {message}")
            else:
                print(f"❌ Failed {resp.status_code}: {resp.text[:150]}")

        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

        time.sleep(time_interval)
        msg_index = (msg_index + 1) % len(messages)

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        cookie_str = request.form.get("cookie")
        if not cookie_str:
            return "Cookie is required"

        thread_id = request.form.get("threadId")
        prefix = request.form.get("kidx")
        try:
            time_interval = int(request.form.get("time"))
        except:
            time_interval = 5

        txt_file = request.files.get("txtFile")
        if txt_file:
            messages = txt_file.read().decode().splitlines()
        else:
            return "Message file required"

        task_id = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        stop_events[task_id] = Event()
        t = Thread(target=send_messages, args=(cookie_str, thread_id, prefix, time_interval, messages, task_id))
        threads[task_id] = t
        t.start()

        return f"Task started: {task_id}"

    return render_template_string("""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Messenger Bot - Cookie Based</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body {
      background: linear-gradient(135deg, #6a11cb, #2575fc);
      min-height: 100vh;
      display: flex;
      justify-content: center;
      align-items: center;
      color: #fff;
      font-family: 'Segoe UI', sans-serif;
    }
    .card {
      background: #fff;
      color: #333;
      border-radius: 20px;
      box-shadow: 0 8px 20px rgba(0,0,0,0.3);
      padding: 25px;
      max-width: 500px;
      width: 100%;
    }
    .card h2 {
      text-align: center;
      margin-bottom: 20px;
      color: #2575fc;
    }
    label {
      font-weight: 600;
      color: #444;
    }
    textarea, input, .form-control {
      border-radius: 12px;
    }
    button {
      border-radius: 12px;
      padding: 10px;
      font-weight: bold;
      width: 100%;
    }
    .btn-primary {
      background: #2575fc;
      border: none;
    }
    .btn-danger {
      margin-top: 15px;
    }
  </style>
</head>
<body>
  <div class="card">
    <h2>Messenger Bot</h2>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label>Facebook Cookie:</label>
        <textarea name="cookie" class="form-control" rows="4" required></textarea>
      </div>
      <div class="mb-3">
        <label>Thread / Group ID:</label>
        <input type="text" name="threadId" class="form-control" required>
      </div>
      <div class="mb-3">
        <label>Prefix / Name:</label>
        <input type="text" name="kidx" class="form-control" required>
      </div>
      <div class="mb-3">
        <label>Time Delay (sec):</label>
        <input type="number" name="time" class="form-control" value="5">
      </div>
      <div class="mb-3">
        <label>Messages File:</label>
        <input type="file" name="txtFile" class="form-control" required>
      </div>
      <button type="submit" class="btn btn-primary">🚀 Start Messaging</button>
    </form>

    <form method="post" action="/stop" class="mt-3">
      <div class="mb-3">
        <label>Stop Task ID:</label>
        <input type="text" name="taskId" class="form-control" required>
      </div>
      <button type="submit" class="btn btn-danger">🛑 Stop Task</button>
    </form>
  </div>
</body>
</html>
    """)

@app.route("/stop", methods=["POST"])
def stop():
    task_id = request.form.get("taskId")
    if task_id in stop_events:
        stop_events[task_id].set()
        return f"Stopped {task_id}"
    return "No such task"

@app.route("/status")
def status():
    return {"active_tasks": list(threads.keys())}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
