"""Read the Path of Exile wiki (poewiki.net) through its MediaWiki API. Python 3.8+, stdlib only.

The article pages (/wiki/...) sit behind bot protection and refuse automated clients; the API does not.
This script only ever talks to the API, identifies itself honestly, and spaces its requests.

  python wiki.py search "Pearl of Tsoatha"            find page titles
  python wiki.py sections "Battlemage"                list a page's sections
  python wiki.py page "Battlemage"                    page as plain text (rendered, tables flattened)
  python wiki.py page "List of tattoos" --section 2   one section only (number from `sections`)
  python wiki.py page "Battlemage" --wikitext         raw wikitext instead of rendered text
  python wiki.py item "Pearl of Tsoatha" "Unholy Accomplice"
                                                      is it in game / still dropping / when added or removed
  python wiki.py fields items                         columns of a Cargo table
  python wiki.py cargo --tables items --fields "items.name,items.drop_enabled" \
         --where 'items.class_id="Belt" AND items.rarity_id="unique"' --limit 50

Add --json to any command for the raw API response.
"""
import argparse, html, io, json, os, re, sys, tempfile, time, urllib.parse, urllib.request

API = "https://www.poewiki.net/w/api.php"
UA = "poe-wiki-skill/1.0 (MediaWiki API client; low volume)"
MIN_GAP = 2.0  # seconds between requests, across processes
STAMP = os.path.join(tempfile.gettempdir(), "poe_wiki_skill.stamp")


def _pace():
    try:
        wait = os.path.getmtime(STAMP) + MIN_GAP - time.time()
        if 0 < wait <= MIN_GAP:
            time.sleep(wait)
    except OSError:
        pass
    try:
        with open(STAMP, "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def api(**params):
    params["format"] = "json"
    _pace()
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        d = json.loads(raw)
    except ValueError:
        raise SystemExit("The API did not return JSON (first 300 chars): " + raw[:300])
    if "error" in d:
        hint = " (a Cargo query fails like this when a field or table name does not exist; check with `fields <table>`)" if "MWException" in str(d["error"].get("code")) else ""
        raise SystemExit("API error: %s: %s%s" % (d["error"].get("code"), d["error"].get("info"), hint))
    return d


_SPAN = re.compile(r"<(/?)span\b")


def _drop_hoverboxes(h):
    """Remove the item/skill tooltip popups the wiki embeds after every link (they flood the text)."""
    out, i, key = [], 0, "hoverbox__display"
    while True:
        j = h.find(key, i)
        if j < 0:
            out.append(h[i:]); break
        start = h.rfind("<span", i, j)
        if start < 0:
            out.append(h[i:j + len(key)]); i = j + len(key); continue
        out.append(h[i:start])
        depth, k = 0, start
        while True:
            m = _SPAN.search(h, k)
            if not m:
                k = len(h); break
            depth += -1 if m.group(1) else 1
            k = m.end()
            if depth == 0:
                k = h.find(">", k) + 1; break
        i = k
    return "".join(out)


def to_text(h):
    """Rendered HTML -> readable plain text. Tables become one line per row, cells joined by ' | '."""
    if "&lt;" in h and "<" not in h:
        h = html.unescape(h)          # Cargo fields come back with their HTML escaped
    h = _drop_hoverboxes(h.replace("&#95;", "_"))
    h = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", h)
    h = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", h)
    h = re.sub(r"(?s)<(script|style)[^>]*>.*?</\1>", "", h)
    h = re.sub(r"(?s)<!--.*?-->", "", h)
    h = re.sub(r'(?s)<span class="mw-editsection">.*?</span></span>', "", h)
    h = re.sub(r"(?s)<h([1-6])[^>]*>(.*?)</h\1>", lambda m: "\n\n%s %s %s\n" % ("=" * int(m.group(1)), re.sub(r"<[^>]+>", "", m.group(2)).strip(), "=" * int(m.group(1))), h)
    h = re.sub(r"(?s)</t[dh]>\s*<t[dh][^>]*>", " | ", h)
    h = re.sub(r"(?i)<br\s*/?>", " / ", h)
    h = re.sub(r"(?i)</(tr|p|div|li|ul|ol|table|dd|dt)>", "\n", h)
    h = re.sub(r"(?i)<li[^>]*>", "- ", h)
    t = html.unescape(re.sub(r"<[^>]+>", "", h))
    t = re.sub(r"[ \t\xa0]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def cmd_search(a):
    d = api(action="query", list="search", srsearch=a.query, srlimit=a.limit)
    if a.json: return d
    hits = d["query"]["search"]
    print("%d total hits, showing %d" % (d["query"]["searchinfo"]["totalhits"], len(hits)))
    for h in hits:
        print("- %s  (%s)\n    %s" % (h["title"], h["timestamp"][:10], to_text(h.get("snippet", ""))))


def cmd_sections(a):
    d = api(action="parse", page=a.title, prop="sections", redirects=1)
    if a.json: return d
    print(d["parse"]["title"])
    for s in d["parse"]["sections"]:
        print("  %s%s. %s" % ("  " * (int(s["toclevel"]) - 1), s["index"], s["line"]))


def cmd_page(a):
    p = dict(action="parse", page=a.title, prop="wikitext" if a.wikitext else "text", redirects=1)
    if a.section is not None: p["section"] = a.section
    d = api(**p)
    if a.json: return d
    body = d["parse"]["wikitext" if a.wikitext else "text"]["*"]
    out = body if a.wikitext else to_text(body)
    print("# %s\n# https://www.poewiki.net/wiki/%s\n" % (d["parse"]["title"], urllib.parse.quote(d["parse"]["title"].replace(" ", "_"))))
    if a.max and len(out) > a.max:
        out = out[:a.max] + "\n\n[truncated at %d of %d characters; use --section or --max 0]" % (a.max, len(out))
    print(out)


ITEM_FIELDS = "items.name,items.class_id,items.rarity_id,items.drop_enabled,items.is_in_game,items.release_version,items.removal_version,items.drop_text"


def cmd_item(a):
    names = ",".join('"%s"' % n.replace('"', '\\"') for n in a.names)
    d = api(action="cargoquery", tables="items", fields=ITEM_FIELDS, where="items.name IN (%s)" % names, limit=100)
    if a.json: return d
    seen, found = set(), set()
    for row in d.get("cargoquery", []):
        t = row["title"]; key = json.dumps(t, sort_keys=True)
        if key in seen: continue
        seen.add(key); found.add(t["name"])
        dropping = t.get("drop enabled") == "1"; ingame = t.get("is in game") == "1"
        if not ingame: verdict = "NOT IN GAME"
        elif dropping: verdict = "obtainable (drop enabled)"
        else: verdict = "DROP DISABLED — legacy, only exists in permanent leagues" + ((" (removed %s)" % t["removal version"]) if t.get("removal version") else "")
        print("%s  [%s%s]\n    %s\n    released %s%s%s" % (
            t["name"], t.get("class id") or "?", (", " + t["rarity id"]) if t.get("rarity id") else "", verdict,
            t.get("release version") or "?", (", removed " + t["removal version"]) if t.get("removal version") else "",
            ("\n    source: " + to_text(t["drop text"])) if t.get("drop text") else ""))
    for n in a.names:
        if n not in found:
            like = api(action="cargoquery", tables="items", fields="items.name", group_by="items.name", limit=8,
                       where='items.name LIKE "%%%s%%"' % n.replace('"', ""))
            near = [r["title"]["name"] for r in like.get("cargoquery", [])]
            print("%s\n    no item with exactly this name%s" % (
                n, ("; did you mean: " + "; ".join(near)) if near else " and nothing similar (support gems end in ' Support'; try `search`)"))


def cmd_fields(a):
    d = api(action="cargofields", table=a.table)
    if a.json: return d
    for k, v in sorted(d["cargofields"].items()):
        print("%-40s %s%s" % (k, v.get("type"), " (list)" if "isList" in v else ""))


def cmd_cargo(a):
    p = dict(action="cargoquery", tables=a.tables, fields=a.fields, limit=a.limit)
    for k, v in (("where", a.where), ("join_on", a.join), ("order_by", a.order), ("group_by", a.group), ("offset", a.offset)):
        if v: p[k] = v
    d = api(**p)
    if a.json: return d
    rows = [r["title"] for r in d.get("cargoquery", [])]
    print("%d rows" % len(rows))
    for r in rows:
        print(" | ".join("%s=%s" % (k, to_text(str(v)) if v is not None else "") for k, v in r.items()))


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="print the raw API response")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--limit", type=int, default=8); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("sections"); s.add_argument("title"); s.set_defaults(fn=cmd_sections)
    s = sub.add_parser("page"); s.add_argument("title"); s.add_argument("--section", type=int); s.add_argument("--wikitext", action="store_true")
    s.add_argument("--max", type=int, default=12000, help="truncate output to this many characters (0 = no limit)"); s.set_defaults(fn=cmd_page)
    s = sub.add_parser("item"); s.add_argument("names", nargs="+"); s.set_defaults(fn=cmd_item)
    s = sub.add_parser("fields"); s.add_argument("table"); s.set_defaults(fn=cmd_fields)
    s = sub.add_parser("cargo"); s.add_argument("--tables", required=True); s.add_argument("--fields", required=True); s.add_argument("--where")
    s.add_argument("--join"); s.add_argument("--order"); s.add_argument("--group"); s.add_argument("--limit", type=int, default=50); s.add_argument("--offset", type=int); s.set_defaults(fn=cmd_cargo)
    a = ap.parse_args()
    if not a.cmd:
        ap.print_help(); return
    d = a.fn(a)
    if d is not None:
        print(json.dumps(d, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
