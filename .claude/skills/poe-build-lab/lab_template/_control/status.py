"""Controller: one-screen status of the running round.

    python status.py [tail_chars=900] [-v] [--port 8765] [--watch <dir> ...]

Shows registered builds (and files in builds\\ that were never registered), delivered documents, board
threads and access counts (-v prints the posts), the tail of each unit's journal, and — for every --watch
directory — files created there since the round started (use it for places units must not write to,
e.g. the Path of Building install folder).
"""
import glob, io, json, os, sys, time, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__)); LAB = os.path.dirname(HERE)
args = sys.argv[1:]
verbose = "-v" in args
port = int(args[args.index("--port") + 1]) if "--port" in args else 8765
watch = [args[i + 1] for i, x in enumerate(args) if x == "--watch" and i + 1 < len(args)]
nums = [x for x in args if x.isdigit() and (args.index(x) == 0 or args[args.index(x) - 1] != "--port")]
tail = int(nums[0]) if nums else 900


def read(p, default=""):
    return io.open(p, encoding="utf-8", errors="replace").read() if os.path.exists(p) else default


start_epoch = float(read(os.path.join(HERE, "start_epoch.txt"), "0") or 0)
elapsed = (time.time() - start_epoch) / 60 if start_epoch else 0
print("now %s | round started %s | %d min elapsed" % (time.strftime("%H:%M"), read(os.path.join(HERE, "start_time.txt")).strip() or "?", elapsed))
units = sorted(x for x in os.listdir(os.path.join(LAB, "units")) if os.path.isdir(os.path.join(LAB, "units", x))) if os.path.isdir(os.path.join(LAB, "units")) else []
reg = json.loads(read(os.path.join(HERE, "registry.json"), '{"builds": []}'))["builds"]

print("\n== builds")
for b in sorted(reg, key=lambda b: (b["unit"], b["ts"])):
    f = os.path.join(LAB, "units", b["unit"], "builds", b["name"] + ".xml")
    print("  %s %-36s registered %s  saved=%-5s | %s" % (b["unit"], b["name"], time.strftime("%H:%M", time.localtime(b["ts"])), os.path.exists(f), b["purpose"][:100]))
for u in units:
    names = set(b["name"] for b in reg if b["unit"] == u)
    extra = [os.path.basename(x) for x in glob.glob(os.path.join(LAB, "units", u, "builds", "*")) if os.path.splitext(os.path.basename(x))[0] not in names]
    if extra:
        print("  !! unit %s has files in builds\\ that were never registered: %s" % (u, extra))
    docs = [os.path.basename(x) for x in glob.glob(os.path.join(LAB, "units", u, "docs", "*"))]
    if docs:
        print("  unit %s docs: %s" % (u, docs))

print("\n== board")
try:
    k = read(os.path.join(HERE, "admin_key.txt")).strip()
    r = urllib.request.Request("http://127.0.0.1:%d/admin/stats" % port); r.add_header("X-Board-Key", k)
    d = json.loads(urllib.request.urlopen(r, timeout=5).read().decode())
    print("  access:", ", ".join("%s %s/%s=%d" % (a["unit"], a["kind"], a["result"], a["n"]) for a in d["access"] if a["unit"] != "-") or "(none yet)")
    for t in d["threads"]:
        print("  #%d [%s/%s] %s | %s %s replies=%d%s" % (t["id"], t["type"], t["status"], t["title"], t["author"], time.strftime("%H:%M", time.localtime(t["created"])), t["replies"], (" outcome=" + t["outcome"]) if t.get("outcome") else ""))
        if verbose:
            for p in t["posts"]:
                print("      %s: %s" % (p["author"], p["content"][:1200].replace("\n", " ")))
except Exception as e:
    print("  board not reachable on port %d (%s). If it should be running, restart it; threads are kept in board\\board.db." % (port, e))

for w in watch:
    new = [os.path.basename(x) for x in glob.glob(os.path.join(w, "*")) if os.path.isfile(x) and os.path.getmtime(x) > start_epoch]
    print("\n== new files in %s since the round started: %s" % (w, new or "none"))

if tail:
    for u in units:
        p = os.path.join(LAB, "units", u, "notes", "journal.md")
        s = read(p)
        print("\n== journal %s (%d chars, modified %s) tail:" % (u, len(s), time.strftime("%H:%M", time.localtime(os.path.getmtime(p))) if s else "-"))
        print(s[-tail:])
