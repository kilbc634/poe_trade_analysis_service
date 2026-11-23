# -*- coding: utf-8 -*-
"""Read the modifier tables of a poedb.tw base-item page (families, tiers, item levels, weights).

    python poedb_mods.py Searching_Eye_Jewel                      # group overview (totals per group)
    python poedb_mods.py Searching_Eye_Jewel --group "Base Suffix"  # every family in one group
    python poedb_mods.py Searching_Eye_Jewel --group "Base Suffix" --find accuracy --ilvl 85
    python poedb_mods.py https://poedb.tw/us/Vaal_Regalia --group "Base Prefix" --tiers
    python poedb_mods.py Searching_Eye_Jewel --json > out.json

The tables are built by the page's own script, so a plain HTTP fetch does not contain them; this drives playwright-cli
(headless is fine) and reads the rendered DOM. Results are cached for 6 hours (--refresh to bypass).
Python 3.8+, standard library only. Requires the `playwright-cli` command.
"""
import argparse, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
JS = os.path.join(HERE, "poedb_mods.js")
CACHE_DIR = os.environ.get("POEDB_CACHE") or os.path.join(tempfile.gettempdir(), "poedb-mods")
SESSION = "poedb"
TTL = 6 * 3600


def cli():
    exe = shutil.which("playwright-cli") or shutil.which("playwright-cli.cmd")
    if not exe and os.name == "nt":
        cand = os.path.join(os.environ.get("APPDATA", ""), "npm", "playwright-cli.cmd")
        exe = cand if os.path.exists(cand) else None
    if not exe:
        sys.exit("playwright-cli not found (npm install -g @playwright/cli)")
    return exe


def run(args, timeout=90):
    r = subprocess.run([cli(), "-s=" + SESSION] + args, capture_output=True, timeout=timeout)
    return r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def to_url(page, lang):
    if page.startswith("http"):
        return page
    return "https://poedb.tw/%s/%s" % (lang, page.strip().replace(" ", "_"))


def fetch(url, refresh=False, headed=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    cf = os.path.join(CACHE_DIR, hashlib.sha1(url.encode()).hexdigest()[:16] + ".json")
    if not refresh and os.path.exists(cf) and time.time() - os.path.getmtime(cf) < TTL:
        return json.load(open(cf, encoding="utf-8")), True
    try:
        run(["open", url] + (["--headed"] if headed else []))
        out, err = run(["--raw", "run-code", "--filename=" + JS])
    finally:
        run(["close"])
    start = out.find("{")
    if start < 0:
        sys.exit("no data returned from the page:\n" + (out + err)[:800])
    data = json.loads(out[start:])
    if data.get("waited") != "ok" or not data.get("groups"):
        sys.exit("the modifier tables did not render (waited=%s, groups=%d). Title: %s\n"
                 "Check the page name, or retry with --headed." % (data.get("waited"), len(data.get("groups") or []), data.get("title")))
    json.dump(data, open(cf, "w", encoding="utf-8"), ensure_ascii=False)
    return data, False


def num(s):
    m = re.search(r"-?\d+", s or "")
    return int(m.group()) if m else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("page", help="poedb page name (Searching_Eye_Jewel) or full URL")
    ap.add_argument("--lang", default="us", help="site language segment for bare page names: us (default), tw, cn …")
    ap.add_argument("--group", help='group name, e.g. "Base Suffix" (case-insensitive substring; omit for the overview)')
    ap.add_argument("--find", help="only families whose text contains this (case-insensitive)")
    ap.add_argument("--ilvl", type=int, help="item level of your base: tiers above it are dropped and weights/percentages recomputed")
    ap.add_argument("--tiers", action="store_true", help="print every tier of each listed family")
    ap.add_argument("--json", action="store_true", help="raw extracted data as JSON")
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument("--headed", action="store_true", help="open a visible browser window")
    a = ap.parse_args()
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    url = to_url(a.page, a.lang)
    data, cached = fetch(url, a.refresh, a.headed)
    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=1))
        return
    print("# %s%s\n# %s" % (data["title"], "  [cached]" if cached else "", data["url"]))

    def fam_weight(f):
        """(weight, tiers kept) of a family at the requested item level"""
        tiers = f["tiers"]
        if a.ilvl is None or not tiers:
            return num(f["weight"]), tiers
        kept = [t for t in tiers if num(t["ilvl"]) <= a.ilvl]
        return sum(num(t["weight"]) for t in kept), kept

    if not a.group:
        print("\n%-24s %8s %14s" % ("group", "families", "total weight" + ("" if a.ilvl is None else " @ilvl %d" % a.ilvl)))
        for g in data["groups"]:
            print("%-24s %8d %14d" % (g["name"], len(g["families"]), sum(fam_weight(f)[0] for f in g["families"])))
        print('\npick one with --group "<name>"')
        return
    gs = [g for g in data["groups"] if a.group.lower() == g["name"].lower()] or [g for g in data["groups"] if a.group.lower() in g["name"].lower()]
    if len(gs) != 1:
        sys.exit("--group %r matches %s; available: %s" % (a.group, [g["name"] for g in gs], ", ".join(g["name"] for g in data["groups"])))
    g = gs[0]
    total = sum(fam_weight(f)[0] for f in g["families"])
    print("\n== %s | %d families | total weight %d%s" % (g["name"], len(g["families"]), total, "" if a.ilvl is None else " at item level %d" % a.ilvl))
    print("%7s %7s %5s %5s  %s" % ("weight", "chance", "ilvl", "tiers", "top tier text [tags]"))
    for f in g["families"]:
        if a.find and a.find.lower() not in f["text"].lower():
            continue
        w, kept = fam_weight(f)
        top = kept[-1] if kept else None      # poedb lists tiers worst-first
        text = top["text"] if (a.ilvl is not None and top) else f["text"]
        print("%7d %6.3f%% %5s %5d  %s [%s]" % (w, 100.0 * w / total if total else 0, (top["ilvl"] if top and a.ilvl is not None else f["ilvl"]), len(kept),
                                               text, ",".join(f["tags"])))
        if a.tiers or a.find:
            for t in f["tiers"]:
                dropped = a.ilvl is not None and num(t["ilvl"]) > a.ilvl
                tw = num(t["weight"])
                print("            %-4s %-22s ilvl %-3s weight %-5d %6.3f%% of group  %s%s" % (
                    t["tier"], t["name"], t["ilvl"], tw, 100.0 * tw / total if total and not dropped else 0, t["text"], "   (above your item level)" if dropped else ""))


if __name__ == "__main__":
    main()
