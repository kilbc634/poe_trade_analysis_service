"""Self-test of the lab tooling on a throwaway copy (nothing in the real lab is touched). Python 3.8+.

    python smoke_test.py

Checks the board (invisible without a key, quotas, thread lifecycle, who may close a thread), the build
registry, the pacing gate and brief stamping. Run it once after copying the lab template to a new folder.
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request

LAB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8799
tmp = os.path.join(tempfile.mkdtemp(), "lab")
shutil.copytree(LAB, tmp, ignore=shutil.ignore_patterns("units", "round*", "board.db", "admin_key.txt", "registry.json", "snapshots",
                                                        "reveal_*", "start_*", "slot_*", "__pycache__", "PREMISE.md", "shared"))
srv = subprocess.Popen([sys.executable, os.path.join(tmp, "board", "server.py"), "--port", str(PORT)], stdout=subprocess.PIPE)
srv.stdout.readline()
ADMIN = open(os.path.join(tmp, "_control", "admin_key.txt")).read().strip()
fails = []


def call(key, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (PORT, path), method=method)
    if key: req.add_header("X-Board-Key", key)
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {}


def check(name, cond, got=None):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> %r" % (got,)))
    if not cond: fails.append(name)


def run(*args):
    return subprocess.run([sys.executable] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, encoding="utf-8", errors="replace")


try:
    s, r = call(None, "GET", "/threads"); check("no key -> 404", s == 404, s)
    s, r = call("wrong", "GET", "/help"); check("bad key -> 404", s == 404, s)
    call(ADMIN, "POST", "/admin/cfg", {"post_interval_s": 0})
    A = call(ADMIN, "POST", "/admin/units", {"name": "Unit-A"})[1]["key"]
    B = call(ADMIN, "POST", "/admin/units", {"name": "Unit-B"})[1]["key"]
    s, r = call(A, "GET", "/admin/stats"); check("unit cannot reach admin", s == 404, s)
    long = "This is a body long enough to pass every minimum-length rule, with a concrete detail 12345 and some more words to clear the sixty character summary floor."
    s, r = call(A, "POST", "/threads", {"type": "question", "title": "t1", "content": long}); tid = r.get("thread_id")
    check("post thread", r.get("ok") and tid, r)
    s, r = call(A, "POST", "/threads", {"type": "bogus", "title": "x", "content": long}); check("bad type refused", not r["ok"], r)
    s, r = call(A, "POST", "/threads/%d/replies" % tid, {"content": long}); check("author cannot follow own opening post", not r["ok"], r)
    s, r = call(B, "POST", "/threads/%d/replies" % tid, {"content": "thx"}); check("short reply refused", not r["ok"], r)
    s, r = call(B, "POST", "/threads/%d/replies" % tid, {"content": long}); check("reply ok", r["ok"], r)
    s, r = call(B, "POST", "/threads/%d/replies" % tid, {"content": long}); check("consecutive reply refused", not r["ok"], r)
    s, r = call(A, "GET", "/threads?filter=my_threads_with_new_replies"); check("mine shows new reply", len(r.get("threads", [])) == 1, r)
    s, r = call(A, "GET", "/threads/%d" % tid); check("show has 2 posts", len(r["thread"]["posts"]) == 2, r)
    s, r = call(B, "POST", "/threads/%d/resolve" % tid, {"outcome": "answered", "summary": long}); check("non-author cannot resolve", not r["ok"], r)
    s, r = call(A, "POST", "/threads/%d/resolve" % tid, {"outcome": "answered", "summary": "short"}); check("short summary refused", not r["ok"], r)
    s, r = call(A, "POST", "/threads/%d/resolve" % tid, {"outcome": "answered", "summary": long}); check("resolve ok", r["ok"], r)
    s, r = call(B, "POST", "/threads/%d/replies" % tid, {"content": long}); check("resolved is read-only", not r["ok"], r)
    s, r = call(B, "GET", "/threads"); check("resolved still listed by default", len(r["threads"]) == 1 and r["threads"][0]["status"] == "resolved", r)
    s, r = call(B, "GET", "/threads?status=open"); check("status=open filter excludes it", len(r["threads"]) == 0, r)
    s, r = call(B, "GET", "/search?q=12345"); check("search finds it", len(r["threads"]) == 1, r)
    lim = None
    for i in range(8):
        s, r = call(B, "GET", "/threads")
        if not r["ok"]: lim = r; break
    check("read rate limit is a soft notice", lim is not None and "notice" in lim, lim)
    call(ADMIN, "POST", "/admin/cfg", {"post_interval_s": 240})
    s, r = call(A, "POST", "/threads", {"type": "deadend", "title": "t2", "content": long})
    s, r2 = call(A, "POST", "/threads", {"type": "deadend", "title": "t3", "content": long})
    check("write quota soft notice", (not r2["ok"]) and "retry_after_s" in r2, (r, r2))
    call(ADMIN, "POST", "/admin/cfg", {"stale_after_s": 1, "post_interval_s": 0, "read_max": 999})
    s, r = call(A, "POST", "/threads", {"type": "hypothesis", "title": "t4", "content": long}); t4 = r["thread_id"]
    time.sleep(1.5)
    s, r = call(B, "GET", "/threads/%d" % t4); check("goes stale", r["thread"]["status"] == "stale", r["thread"]["status"])
    s, r = call(B, "POST", "/threads/%d/replies" % t4, {"content": long})
    s, r = call(B, "GET", "/threads/%d" % t4); check("reply reopens stale", r["thread"]["status"] == "open", r["thread"]["status"])
    s, r = call(B, "GET", "/threads"); st = [t["status"] for t in r["threads"]]
    check("every state listed, active first", len(st) >= 2 and "resolved" in st and st == sorted(st, key=lambda x: ["open", "stale", "resolved"].index(x)), st)
finally:
    srv.kill()

# brief stamping, registry, pacing gate
skills = os.path.join(tmp, "fake_skills"); os.makedirs(skills)
with open(os.path.join(tmp, "_control", "PREMISE.md"), "w", encoding="utf-8") as f:
    f.write("Core: <<fill me>>")
r = run(os.path.join(tmp, "_control", "setup_units.py"), "--skills", skills, "--units", "A,B")
check("setup refuses an unfilled premise", r.returncode != 0 and "placeholder" in r.stdout, r.stdout)
with open(os.path.join(tmp, "_control", "PREMISE.md"), "w", encoding="utf-8") as f:
    f.write("Core mechanic: something. Given facts: none.")
r = run(os.path.join(tmp, "_control", "setup_units.py"), "--skills", skills, "--units", "A,B")
check("setup stamps the briefs", r.returncode == 0 and os.path.exists(os.path.join(tmp, "units", "B", "AUDITOR_BRIEF.md")), r.stdout)
brief = open(os.path.join(tmp, "units", "A", "BRIEF.md"), encoding="utf-8").read()
check("brief has no leftover placeholders and no board mention", "{" not in brief.replace("{U}", "") and "留言板" not in brief and "board" not in brief.lower(), [w for w in ("留言板", "board") if w in brief.lower()])
reg = os.path.join(tmp, "tools", "registry.py")
r = run(reg, "register", "--unit", "A", "--name", "first-build", "--purpose", "smoke test of registration"); check("register", r.returncode == 0, r.stdout)
r = run(reg, "register", "--unit", "B", "--name", "First_Build", "--purpose", "same name from another unit"); check("duplicate name refused", r.returncode != 0, r.stdout)
r = run(reg, "path", "--unit", "A", "--name", "nope"); check("path refuses an unregistered name", r.returncode != 0, r.stdout)
r = run(reg, "path", "--unit", "A", "--name", "first-build"); check("path gives the save location", r.returncode == 0 and r.stdout.strip().endswith("first-build.xml"), r.stdout)
slot = os.path.join(tmp, "tools", "slot.py")
t0 = time.time(); run(slot, "probe", "2"); run(slot, "probe", "2")
check("pacing gate spaces two calls", time.time() - t0 >= 1.8, time.time() - t0)
r = run(os.path.join(tmp, "_control", "archive_round.py"))
check("archive moves the round away", r.returncode == 0 and os.path.isdir(os.path.join(tmp, "round1", "units", "A")) and not os.path.exists(os.path.join(tmp, "_control", "registry.json")), r.stdout)
shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
print("FAILS:", fails)
sys.exit(1 if fails else 0)
