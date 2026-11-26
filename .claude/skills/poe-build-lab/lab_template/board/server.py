"""Local research message board (threads with a lifecycle). Stdlib only, Python 3.8+.

Pull-only: nothing is ever pushed to a unit. Every request needs the X-Board-Key header;
without a valid key the server answers 404 to everything, so the board stays invisible
until the controller issues a unit its key.

Run:  python server.py [--port 8765]
"""
import argparse, json, os, re, secrets, sqlite3, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
CONTROL = os.path.join(os.path.dirname(HERE), "_control")
DB = os.path.join(HERE, "board.db")
ADMIN_KEY_FILE = os.path.join(CONTROL, "admin_key.txt")

TYPES = {"finding": "發現", "question": "提問", "hypothesis": "假說", "deadend": "死路"}
OUTCOMES = {"verified", "refuted", "undetermined", "answered", "duplicate", "withdrawn"}
CFG = {
    "post_interval_s": 240,      # one write (thread or reply) per unit per this many seconds
    "read_window_s": 600,        # sliding window for reads
    "read_max": 6,               # reads (list/show/search) per window
    "reply_cap": 20,             # replies per thread
    "min_reply_chars": 40,
    "min_summary_chars": 60,
    "stale_after_s": 40 * 60,    # open -> stale after no activity
}
LOCK = threading.Lock()


def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(CONTROL, exist_ok=True)
    if not os.path.exists(ADMIN_KEY_FILE):
        with open(ADMIN_KEY_FILE, "w") as f:
            f.write(secrets.token_hex(16))
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS units(key TEXT PRIMARY KEY, name TEXT UNIQUE, created REAL);
    CREATE TABLE IF NOT EXISTS threads(id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, title TEXT, author TEXT,
        status TEXT, created REAL, last_activity REAL, status_changed REAL, outcome TEXT, summary TEXT, dup_of INTEGER);
    CREATE TABLE IF NOT EXISTS posts(id INTEGER PRIMARY KEY AUTOINCREMENT, thread_id INTEGER, author TEXT, content TEXT,
        links TEXT, created REAL);
    CREATE TABLE IF NOT EXISTS last_read(unit TEXT, thread_id INTEGER, ts REAL, PRIMARY KEY(unit, thread_id));
    CREATE TABLE IF NOT EXISTS access_log(ts REAL, unit TEXT, method TEXT, path TEXT, kind TEXT, result TEXT);
    """)
    c.commit(); c.close()


def sweep(c, now):
    c.execute("UPDATE threads SET status='stale', status_changed=? WHERE status='open' AND ?-last_activity>?",
              (now, now, CFG["stale_after_s"]))
    # there is no archived state: stale and resolved threads stay listed for good
    c.execute("UPDATE threads SET status = CASE WHEN outcome IS NOT NULL THEN 'resolved' ELSE 'stale' END WHERE status='archived'")


def thread_row(c, t, with_posts=False):
    n = c.execute("SELECT COUNT(*) FROM posts WHERE thread_id=?", (t["id"],)).fetchone()[0]
    d = {"id": t["id"], "type": t["type"], "type_label": TYPES.get(t["type"], t["type"]), "title": t["title"],
         "author": t["author"], "status": t["status"], "replies": max(n - 1, 0),
         "created": int(t["created"]), "last_activity": int(t["last_activity"]),
         "minutes_since_activity": int((time.time() - t["last_activity"]) / 60)}
    if t["status"] == "resolved" and t["outcome"]:
        d["outcome"] = t["outcome"]; d["summary"] = t["summary"]
        if t["dup_of"]: d["duplicate_of"] = t["dup_of"]
    if with_posts:
        d["posts"] = [{"n": i, "author": p["author"], "content": p["content"], "links": json.loads(p["links"] or "[]"),
                       "created": int(p["created"])}
                      for i, p in enumerate(c.execute("SELECT * FROM posts WHERE thread_id=? ORDER BY id", (t["id"],)))]
    else:
        first = c.execute("SELECT content FROM posts WHERE thread_id=? ORDER BY id LIMIT 1", (t["id"],)).fetchone()
        d["opening_excerpt"] = (first["content"][:200] + ("…" if len(first["content"]) > 200 else "")) if first else ""
    return d


class H(BaseHTTPRequestHandler):
    server_version = "board/1"

    def log_message(self, *a):
        pass

    def send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n: return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return None

    def who(self, c):
        key = self.headers.get("X-Board-Key", "")
        if key and secrets.compare_digest(key, open(ADMIN_KEY_FILE).read().strip()):
            return "__admin__"
        r = c.execute("SELECT name FROM units WHERE key=?", (key,)).fetchone()
        return r["name"] if r else None

    def audit(self, c, unit, kind, result):
        c.execute("INSERT INTO access_log VALUES(?,?,?,?,?,?)",
                  (time.time(), unit or "-", self.command, self.path[:300], kind, result))

    def soft(self, c, unit, kind, notice, **extra):
        self.audit(c, unit, kind, "limited"); c.commit()
        d = {"ok": False, "notice": notice}; d.update(extra)
        self.send(200, d)

    def read_gate(self, c, unit, now):
        n = c.execute("SELECT COUNT(*) FROM access_log WHERE unit=? AND kind='read' AND result='ok' AND ts>?",
                      (unit, now - CFG["read_window_s"])).fetchone()[0]
        if n >= CFG["read_max"]:
            self.soft(c, unit, "read",
                      "你在過去 %d 分鐘內已經讀了 %d 次留言板。留言板不會主動通知也不需要盯著看，先回去做自己的研究，晚點再來。"
                      % (CFG["read_window_s"] // 60, n), retry_after_s=120)
            return False
        return True

    def write_gate(self, c, unit, now):
        r = c.execute("SELECT MAX(ts) FROM access_log WHERE unit=? AND kind='write' AND result='ok'", (unit,)).fetchone()[0]
        if r and now - r < CFG["post_interval_s"]:
            wait = int(CFG["post_interval_s"] - (now - r))
            self.soft(c, unit, "write", "發文有配額：每 %d 分鐘一則。還要 %d 秒。把這段時間拿去把內容寫得更完整。"
                      % (CFG["post_interval_s"] // 60, wait), retry_after_s=wait)
            return False
        return True

    def handle_any(self):
        with LOCK:
            c = db()
            try:
                self.route(c)
                c.commit()
            finally:
                c.close()

    do_GET = do_POST = handle_any

    def route(self, c):
        now = time.time()
        unit = self.who(c)
        if not unit:
            self.audit(c, None, "denied", "no-key"); c.commit()
            return self.send(404, {"error": "not found"})
        sweep(c, now)
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        admin = unit == "__admin__"

        # ---------------- admin ----------------
        if parts[:1] == ["admin"]:
            if not admin:
                return self.send(404, {"error": "not found"})
            if parts == ["admin", "units"] and self.command == "POST":
                b = self.body() or {}
                key = secrets.token_hex(12)
                try:
                    c.execute("INSERT INTO units VALUES(?,?,?)", (key, b["name"], now))
                except sqlite3.IntegrityError:
                    key = c.execute("SELECT key FROM units WHERE name=?", (b["name"],)).fetchone()["key"]
                return self.send(200, {"ok": True, "name": b["name"], "key": key})
            if parts == ["admin", "log"]:
                since = float(q.get("since", 0))
                rows = [dict(r) for r in c.execute("SELECT * FROM access_log WHERE ts>? ORDER BY ts", (since,))]
                return self.send(200, {"ok": True, "log": rows})
            if parts == ["admin", "stats"]:
                st = [dict(r) for r in c.execute(
                    "SELECT unit, kind, result, COUNT(*) n FROM access_log GROUP BY unit, kind, result ORDER BY unit")]
                th = [thread_row(c, t, True) for t in c.execute("SELECT * FROM threads ORDER BY id")]
                return self.send(200, {"ok": True, "access": st, "threads": th, "cfg": CFG})
            if parts == ["admin", "cfg"] and self.command == "POST":
                for k, v in (self.body() or {}).items():
                    if k in CFG: CFG[k] = v
                return self.send(200, {"ok": True, "cfg": CFG})
            return self.send(404, {"error": "not found"})

        # ---------------- guide ----------------
        if parts == [] or parts == ["help"]:
            self.audit(c, unit, "help", "ok")
            return self.send(200, {"ok": True, "you_are": unit, "types": TYPES, "outcomes": sorted(OUTCOMES), "limits": CFG})

        # ---------------- reads ----------------
        if self.command == "GET" and parts[:1] == ["threads"] and len(parts) == 1:
            if not self.read_gate(c, unit, now): return
            limit = min(int(q.get("limit", 20)), 50)
            if q.get("filter") == "my_threads_with_new_replies":
                rows = c.execute("""SELECT t.* FROM threads t WHERE t.author=? AND EXISTS(
                    SELECT 1 FROM posts p WHERE p.thread_id=t.id AND p.author!=? AND p.created>
                    COALESCE((SELECT ts FROM last_read WHERE unit=? AND thread_id=t.id),0)) ORDER BY t.last_activity DESC LIMIT ?""",
                                 (unit, unit, unit, limit)).fetchall()
            else:
                # default: every thread in every state; active ones sort first
                status = q.get("status", "all")
                sql, args = "SELECT * FROM threads WHERE 1=1", []
                if status != "all":
                    sql += " AND status=?"; args.append(status)
                if q.get("type"): sql += " AND type=?"; args.append(q["type"])
                if q.get("since"): sql += " AND last_activity>?"; args.append(float(q["since"]))
                order = " ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'stale' THEN 1 ELSE 2 END, last_activity DESC LIMIT ?"
                rows = c.execute(sql + order, args + [limit]).fetchall()
            self.audit(c, unit, "read", "ok")
            return self.send(200, {"ok": True, "now": int(now), "threads": [thread_row(c, t) for t in rows]})

        if self.command == "GET" and parts[:1] == ["threads"] and len(parts) == 2 and parts[1].isdigit():
            if not self.read_gate(c, unit, now): return
            t = c.execute("SELECT * FROM threads WHERE id=?", (int(parts[1]),)).fetchone()
            if not t: return self.send(200, {"ok": False, "notice": "沒有這個討論串。"})
            c.execute("INSERT OR REPLACE INTO last_read VALUES(?,?,?)", (unit, t["id"], now))
            self.audit(c, unit, "read", "ok")
            return self.send(200, {"ok": True, "thread": thread_row(c, t, True)})

        if self.command == "GET" and parts == ["search"]:
            if not self.read_gate(c, unit, now): return
            words = [w for w in re.split(r"\s+", q.get("q", "").strip()) if w]
            if not words: return self.send(200, {"ok": False, "notice": "搜尋需要關鍵字 q。"})
            ids = None
            for w in words:
                like = "%" + w + "%"
                s = {r[0] for r in c.execute(
                    "SELECT t.id FROM threads t LEFT JOIN posts p ON p.thread_id=t.id WHERE t.title LIKE ? OR p.content LIKE ? OR t.summary LIKE ?",
                    (like, like, like))}
                ids = s if ids is None else ids & s
            rows = [c.execute("SELECT * FROM threads WHERE id=?", (i,)).fetchone() for i in sorted(ids or [], reverse=True)[:20]]
            self.audit(c, unit, "read", "ok")
            return self.send(200, {"ok": True, "threads": [thread_row(c, t) for t in rows]})

        # ---------------- writes ----------------
        if self.command == "POST" and parts == ["threads"]:
            b = self.body()
            if not b or b.get("type") not in TYPES or not (b.get("title") or "").strip() or len((b.get("content") or "").strip()) < CFG["min_reply_chars"]:
                return self.send(200, {"ok": False, "notice": "需要 type（%s）、title，以及至少 %d 字的 content。"
                                       % ("/".join(TYPES), CFG["min_reply_chars"])})
            if not self.write_gate(c, unit, now): return
            cur = c.execute("INSERT INTO threads(type,title,author,status,created,last_activity,status_changed) VALUES(?,?,?,?,?,?,?)",
                            (b["type"], b["title"].strip()[:200], unit, "open", now, now, now))
            c.execute("INSERT INTO posts(thread_id,author,content,links,created) VALUES(?,?,?,?,?)",
                      (cur.lastrowid, unit, b["content"].strip(), json.dumps(b.get("links") or []), now))
            self.audit(c, unit, "write", "ok")
            return self.send(200, {"ok": True, "thread_id": cur.lastrowid,
                                   "reminder": "你是發起者：有結論時請用 resolve 關閉並附結論摘要。"})

        if self.command == "POST" and len(parts) == 3 and parts[0] == "threads" and parts[1].isdigit():
            t = c.execute("SELECT * FROM threads WHERE id=?", (int(parts[1]),)).fetchone()
            if not t: return self.send(200, {"ok": False, "notice": "沒有這個討論串。"})
            b = self.body() or {}

            if parts[2] == "replies":
                if t["status"] == "resolved":
                    return self.send(200, {"ok": False, "notice": "這個討論串已關閉（唯讀）。要延續請另開新串並在 links 引用 #%d。" % t["id"]})
                content = (b.get("content") or "").strip()
                if len(content) < CFG["min_reply_chars"]:
                    return self.send(200, {"ok": False, "notice": "回覆至少 %d 字，而且要帶新資訊、證據或具體反駁；單純附和或感謝不用發。" % CFG["min_reply_chars"]})
                last = c.execute("SELECT author FROM posts WHERE thread_id=? ORDER BY id DESC LIMIT 1", (t["id"],)).fetchone()
                if last["author"] == unit:
                    return self.send(200, {"ok": False, "notice": "同一串不能連續發言，要等別人回覆之後才能再回。"})
                n = c.execute("SELECT COUNT(*) FROM posts WHERE thread_id=?", (t["id"],)).fetchone()[0] - 1
                if n >= CFG["reply_cap"]:
                    return self.send(200, {"ok": False, "notice": "這串已達 %d 則回覆上限。請發起者總結關閉，或另開新串並引用 #%d。" % (CFG["reply_cap"], t["id"])})
                if not self.write_gate(c, unit, now): return
                c.execute("INSERT INTO posts(thread_id,author,content,links,created) VALUES(?,?,?,?,?)",
                          (t["id"], unit, content, json.dumps(b.get("links") or []), now))
                c.execute("UPDATE threads SET last_activity=?, status='open', status_changed=? WHERE id=?", (now, now, t["id"]))
                self.audit(c, unit, "write", "ok")
                return self.send(200, {"ok": True, "thread_id": t["id"], "reply_n": n + 1})

            if parts[2] == "resolve":
                if t["author"] != unit:
                    return self.send(200, {"ok": False, "notice": "只有發起者能關閉討論串。"})
                if t["status"] == "resolved":
                    return self.send(200, {"ok": False, "notice": "這個討論串已經關閉。"})
                summary = (b.get("summary") or "").strip()
                if b.get("outcome") not in OUTCOMES or len(summary) < CFG["min_summary_chars"]:
                    return self.send(200, {"ok": False, "notice": "需要 outcome（%s）和至少 %d 字的結論摘要，格式：問題或主張／結論／依據／未解決的部分／相關討論串。"
                                           % ("/".join(sorted(OUTCOMES)), CFG["min_summary_chars"])})
                c.execute("UPDATE threads SET status='resolved', status_changed=?, outcome=?, summary=?, dup_of=? WHERE id=?",
                          (now, b["outcome"], summary, b.get("duplicate_of"), t["id"]))
                self.audit(c, unit, "resolve", "ok")
                return self.send(200, {"ok": True, "thread_id": t["id"], "status": "resolved"})

        self.send(200, {"ok": False, "notice": "不認得這個操作。GET /help 看可用的操作。"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    init()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("board listening on 127.0.0.1:%d" % a.port, flush=True)
    srv.serve_forever()
