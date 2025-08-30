# main.py
import os, time, collections, re
from threading import Thread, Event
from flask import Flask, request, render_template_string, jsonify
import requests

app = Flask(__name__)
app.debug = False

# tasks store
tasks = {}
LOG_MAX = 300

# ---------- helpers ----------
def read_lines_from_file_storage(fobj):
    data = fobj.read()
    if isinstance(data, bytes):
        text = data.decode('utf-8-sig', errors='ignore')
    else:
        text = str(data)
    return [ln.strip() for ln in text.splitlines() if ln.strip()]

def extract_post_id(maybe_url_or_id: str):
    s = (maybe_url_or_id or "").strip()
    if not s:
        return s
    # case: uidXXXXX_postYYYY -> return Y
    if s.startswith("uid") and "_" in s:
        return s.split("_")[-1]
    # case: user_post format like 1000_2000 -> return second part if numeric
    if "_" in s:
        parts = s.split("_")
        if parts[-1].isdigit():
            return parts[-1]
    # look for common URL patterns
    m = re.search(r'(?:posts/|permalink/|story_fbid=|fbid=|photo.php\?fbid=)(\d+)', s)
    if m:
        return m.group(1)
    # fallback: find long digit sequences
    digits = re.findall(r'\d{6,}', s)
    if digits:
        return digits[-1]
    return s

def append_log(task_id, line):
    if task_id not in tasks:
        return
    dq = tasks[task_id]["logs"]
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    dq.append(f"[{ts}] {line}")
    if len(dq) > LOG_MAX:
        dq.popleft()

def post_comment(token, post_id, message):
    url = f"https://graph.facebook.com/v15.0/{post_id}/comments"
    try:
        r = requests.post(url, data={"access_token": token, "message": message}, timeout=15)
    except Exception as e:
        return False, {"error": str(e)}
    try:
        j = r.json()
    except Exception:
        return (r.status_code == 200), {"status_code": r.status_code, "text": r.text[:400]}
    if r.status_code == 200 and "id" in j:
        return True, j
    return False, j

# ---------- worker ----------
def worker_loop(task_id):
    meta = tasks[task_id]["meta"]
    tokens = tasks[task_id]["tokens"]  # list of {"token":..., "valid":True}
    messages = tasks[task_id]["messages"]
    prefix = meta.get("prefix", "").strip()
    post_id = meta["post_id"]
    interval = meta.get("interval", 10)
    stop_ev = tasks[task_id]["stop"]

    append_log(task_id, f"Worker started → post_id={post_id}, interval={interval}s, tokens={len(tokens)}")
    msg_idx = 0
    tk_idx = 0
    consecutive_fail = 0

    while not stop_ev.is_set():
        # choose next valid token
        valid_tokens = [t for t in tokens if t.get("valid", True)]
        if not valid_tokens:
            append_log(task_id, "No valid tokens left — stopping.")
            break

        token_obj = valid_tokens[tk_idx % len(valid_tokens)]
        token = token_obj["token"]

        message = (prefix + " " + messages[msg_idx]).strip()
        ok, resp = post_comment(token, post_id, message)
        if ok:
            append_log(task_id, f"✅ Comment posted: \"{message}\" (id={resp.get('id')})")
            consecutive_fail = 0
        else:
            # error handling
            err = resp.get("error") if isinstance(resp, dict) else resp
            append_log(task_id, f"❌ Failed: {err}")
            consecutive_fail += 1
            # mark invalid token on OAuthException / code 190
            if isinstance(resp, dict) and "error" in resp:
                try:
                    code = resp["error"].get("code")
                    msg = resp["error"].get("message","")
                    if code == 190 or "OAuthException" in str(msg):
                        # find token_obj in tasks[task_id]["tokens"] and mark invalid
                        for t in tasks[task_id]["tokens"]:
                            if t["token"] == token:
                                t["valid"] = False
                                append_log(task_id, f"🚫 Token marked invalid: {token[:8]}...")
                                break
                except Exception:
                    pass
            # backoff on repeated failures
            if consecutive_fail >= 3:
                backoff = min(300, 5 * (2 ** (consecutive_fail - 3)))
                append_log(task_id, f"Multiple errors — backing off {backoff}s")
                for _ in range(backoff):
                    if stop_ev.is_set(): break
                    time.sleep(1)

        # advance
        msg_idx = (msg_idx + 1) % len(messages)
        tk_idx = (tk_idx + 1) % max(1, len(tokens))

        # sleep with early stop check
        for _ in range(int(max(1, interval))):
            if stop_ev.is_set():
                break
            time.sleep(1)

    append_log(task_id, "Worker finished.")
    tasks[task_id]["meta"]["finished"] = True

# ---------- UI ----------
INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Post Server by Aarav Shrivastava</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: linear-gradient(135deg,#2563eb,#1e3a8a); color:#fff; font-family: 'Segoe UI', Roboto, sans-serif; padding:12px; }
    .card { margin:0 auto; max-width:720px; padding:18px; border-radius:14px; background:#fff; color:#111; box-shadow:0 8px 25px rgba(0,0,0,0.25); }
    h3 { color:#1e3a8a; font-weight:700; }
    label { font-weight:600; color:#111827; }
    .muted { color:#6b7280; font-size:0.9rem; }
    footer { text-align:center; margin-top:14px; color:#dbeafe; }
    @media (max-width:576px){ .card{padding:14px} h3{font-size:1.2rem} }
  </style>
</head>
<body>
  <div class="card">
    <h3 class="text-center mb-3">📌 Post Server by Aarav Shrivastava</h3>
    <form method="post" enctype="multipart/form-data">
      <div class="mb-3">
        <label>Token File (.txt)</label>
        <input type="file" name="tokenFile" class="form-control" required>
        <div class="muted">One access token per line (user tokens). Use tokens you own.</div>
      </div>
      <div class="mb-3">
        <label>Post URL or ID (e.g. uid1000_1876... or full post link or numeric id)</label>
        <input type="text" name="postId" class="form-control" required>
      </div>
      <div class="mb-3">
        <label>Prefix (optional)</label>
        <input type="text" name="prefix" class="form-control" placeholder="[BOT]">
      </div>
      <div class="mb-3">
        <label>Delay between comments (seconds)</label>
        <input type="number" name="time" class="form-control" value="10" min="1">
      </div>
      <div class="mb-3">
        <label>Messages File (.txt)</label>
        <input type="file" name="txtFile" class="form-control" required>
        <div class="muted">One comment per line</div>
      </div>
      <button class="btn btn-primary w-100">🚀 Start Task</button>
    </form>

    <hr>
    <form method="post" action="/stop">
      <label>Stop Task ID</label>
      <input type="text" name="taskId" class="form-control mb-2" required>
      <button class="btn btn-danger w-100">🛑 Stop Task</button>
    </form>

    <a class="btn btn-outline-secondary w-100 mt-2" href="/status">📊 View Active Tasks</a>

    <div class="mt-3 small muted">
      Developer: Aarav Shrivastava — <a href="https://wa.me/918809494526" target="_blank">WhatsApp</a>
    </div>
  </div>

  <footer>
    <div>Use only with tokens/accounts you own. Misuse risks account penalties.</div>
  </footer>
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
            return "Missing required fields", 400

        token_lines = read_lines_from_file_storage(token_file)
        tokens_raw = [t for t in token_lines if t]
        if not tokens_raw:
            return "No tokens found", 400

        messages = read_lines_from_file_storage(txt_file)
        if not messages:
            return "Messages file empty", 400

        post_id = extract_post_id(post_input)

        task_id = os.urandom(4).hex()
        stop_ev = Event()
        tasks[task_id] = {
            "thread": None,
            "stop": stop_ev,
            "tokens": [{"token":t, "valid":True} for t in tokens_raw],
            "messages": messages,
            "logs": collections.deque(maxlen=LOG_MAX),
            "meta": {"post_id": post_id, "prefix": prefix, "interval": interval, "started_at": time.time(), "finished": False}
        }

        append_log(task_id, f"Task created. tokens={len(tokens_raw)} messages={len(messages)} post_id={post_id}")
        thread = Thread(target=worker_loop, args=(task_id,), daemon=True)
        tasks[task_id]["thread"] = thread
        thread.start()

        return jsonify({"task_id": task_id, "post_id": post_id, "tokens": len(tokens_raw)})

    return render_template_string(INDEX_HTML)

@app.route("/stop", methods=["POST"])
def stop():
    tid = request.form.get("taskId","").strip()
    if not tid:
        return "taskId required", 400
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
