from flask import Flask, request, render_template_string
import requests
from threading import Thread, Event
import time, random, string, os

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

def send_messages(cookie_str, thread_id, mn, time_interval, messages, task_id):
    stop_event = stop_events[task_id]
    cookies = parse_cookie(cookie_str)
    session = requests.Session()
    session.cookies.update(cookies)

    message_index = 0
    while not stop_event.is_set():
        try:
            message = f"{mn} {messages[message_index]}"
            url = f"https://mbasic.facebook.com/messages/send/"
            data = {
                "tids": f"cid.g.{thread_id}",  # Group thread format
                "body": message,
            }

            resp = session.post(url, data=data, timeout=10)
            if resp.status_code == 200:
                print(f"✅ Sent: {message}")
            else:
                print(f"❌ Failed {resp.status_code}: {resp.text[:100]}")

        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(5)

        time.sleep(time_interval)
        message_index = (message_index + 1) % len(messages)

@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        cookie_str = request.form.get("cookie")
        if not cookie_str:
            return "Cookie is required"

        thread_id = request.form.get("threadId")
        mn = request.form.get("kidx")
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
        t = Thread(target=send_messages, args=(cookie_str, thread_id, mn, time_interval, messages, task_id))
        threads[task_id] = t
        t.start()

        return f"Task started: {task_id}"

    return render_template_string('''
    <h2>Messenger Bot (Cookie Login)</h2>
    <form method="post" enctype="multipart/form-data">
      <label>Facebook Cookie:</label><br>
      <textarea name="cookie" rows="4" cols="50" required></textarea><br><br>
      <label>Thread / Group ID:</label><br>
      <input type="text" name="threadId" required><br><br>
      <label>Prefix / Name:</label><br>
      <input type="text" name="kidx" required><br><br>
      <label>Time Delay (sec):</label><br>
      <input type="number" name="time" value="5"><br><br>
      <label>Messages File:</label><br>
      <input type="file" name="txtFile" required><br><br>
      <button type="submit">Start Messaging</button>
    </form>
    ''')

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
