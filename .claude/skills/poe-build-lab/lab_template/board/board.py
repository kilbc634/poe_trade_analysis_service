"""Command-line client for the research message board. Python 3.8+, stdlib only.

The key comes from --key or the BOARD_KEY environment variable.

  python board.py help
  python board.py read [--status all|open|stale|resolved] [--type finding|question|hypothesis|deadend] [--limit 20]
                                            # default lists every thread, active ones first
  python board.py mine                      # your own threads that got new replies
  python board.py show 12
  python board.py search "keyword"           # full-text search over every thread
  python board.py post --type question --title "..." --file body.md [--links 3,7]
  python board.py reply 12 --file body.md [--links 3]
  python board.py resolve 12 --outcome answered --file summary.md [--duplicate-of 5]

Long text goes in a UTF-8 file passed with --file (or --text for a short one).
"""
import argparse, io, json, os, sys, urllib.request, urllib.parse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def call(a, method, path, body=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (a.port, path), method=method)
    req.add_header("X-Board-Key", a.key or "")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "http": e.code, "notice": e.read().decode("utf-8", "replace")}


def text(a):
    if a.file:
        return open(a.file, encoding="utf-8").read()
    return a.text or ""


def links(a):
    return [int(x) for x in (a.links or "").replace("#", "").split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("BOARD_KEY"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("BOARD_PORT", 8765)))
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("help")
    p = sub.add_parser("read"); p.add_argument("--status", default="all"); p.add_argument("--type"); p.add_argument("--limit", default="20"); p.add_argument("--since")
    sub.add_parser("mine")
    p = sub.add_parser("show"); p.add_argument("id")
    p = sub.add_parser("search"); p.add_argument("q")
    p = sub.add_parser("post"); p.add_argument("--type", required=True); p.add_argument("--title", required=True); p.add_argument("--file"); p.add_argument("--text"); p.add_argument("--links")
    p = sub.add_parser("reply"); p.add_argument("id"); p.add_argument("--file"); p.add_argument("--text"); p.add_argument("--links")
    p = sub.add_parser("resolve"); p.add_argument("id"); p.add_argument("--outcome", required=True); p.add_argument("--file"); p.add_argument("--text"); p.add_argument("--duplicate-of", type=int)
    a = ap.parse_args()
    if a.cmd in (None, "help"):
        r = call(a, "GET", "/help")
    elif a.cmd == "read":
        q = {"status": a.status, "limit": a.limit}
        if a.type: q["type"] = a.type
        if a.since: q["since"] = a.since
        r = call(a, "GET", "/threads?" + urllib.parse.urlencode(q))
    elif a.cmd == "mine":
        r = call(a, "GET", "/threads?filter=my_threads_with_new_replies")
    elif a.cmd == "show":
        r = call(a, "GET", "/threads/%s" % a.id.lstrip("#"))
    elif a.cmd == "search":
        r = call(a, "GET", "/search?" + urllib.parse.urlencode({"q": a.q}))
    elif a.cmd == "post":
        r = call(a, "POST", "/threads", {"type": a.type, "title": a.title, "content": text(a), "links": links(a)})
    elif a.cmd == "reply":
        r = call(a, "POST", "/threads/%s/replies" % a.id.lstrip("#"), {"content": text(a), "links": links(a)})
    elif a.cmd == "resolve":
        r = call(a, "POST", "/threads/%s/resolve" % a.id.lstrip("#"), {"outcome": a.outcome, "summary": text(a), "duplicate_of": a.duplicate_of})
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
