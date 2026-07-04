# -*- coding: utf-8 -*-
"""Multi-slot gear combo optimizer for POE2 trade (多部位配裝暴力窮舉).

Pipeline (see knowledge/tricks.md "Multi-slot gear combos"):
  1. Per slot, run 2-3 searches (cheap broad pool + high-spec pool), price asc.
  2. Fetch ~40 listings per search (deep-fetch hashes [40:100] for the pricier
     tranche of the same query without a new search POST).
  3. Parse into normalized candidates, brute-force the slot cross-product
     locally under joint constraints, report best combo per budget tier.

Hard-won parsing/API facts baked in (don't remove casually):
  - full browser UA required (bare "Mozilla/5.0" -> Cloudflare 403)
  - 429 handling: sleep the FULL Retry-After (penalties run 8-10 min and block
    ALL trade endpoints); space searches ~30s apart in bulk sessions
  - mod text embeds [A|B] wiki brackets -> strip to B before regex
  - crafted mods live inside explicitMods with flags.crafted
  - "Bonded:" runeMod lines are Shaman-ascendancy-only bonus effects of
    normally-working runes -> excluded from scoring (normal lines still count)
  - current defences come from item.extended (es/ev/ar)
  - CURRENCY_RATES go stale: refresh from poe2scout SnapshotPairs
    (knowledge/exchange-rates.md) before trusting price conversion

Usage: edit the CONFIG block, then run. Requires only stdlib.
Scoring shown is for MOM/EB (mana_eq = ES + mana + 2*attributes,
knowledge/mechanics.md); swap `score()` for other builds.
"""
import json, re, time, urllib.request, urllib.error, itertools, os, sys

# ------------------------- CONFIG -------------------------
LEAGUE = "Runes%20of%20Aldur"          # keep URL-encoded; read from setting.py
WORKDIR = "."                           # where s_*.json / pool_*.json land
CURRENCY_RATES = {"divine": 1.0, "exalted": 1/716.6, "chaos": 1/7.376}  # -> div; REFRESH ME (exchange-rates.md)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
# ----------------------------------------------------------

def req(url, data=None):
    """GET/POST with full-UA and 429-aware retry (sleep full Retry-After)."""
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=headers)
    for _ in range(3):
        try:
            with urllib.request.urlopen(r) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = int(e.headers.get("Retry-After", "60"))
                print(f"  429 -> sleeping {ra+5}s (do NOT issue other calls meanwhile)", flush=True)
                time.sleep(ra + 5)
            else:
                raise
    raise RuntimeError("still 429 after retries")

def search(name, query_body):
    """POST a search, save s_<name>.json. Space bulk searches ~30s apart!"""
    j = req(f"https://www.pathofexile.com/api/trade2/search/poe2/{LEAGUE}",
            json.dumps(query_body).encode("utf-8"))
    json.dump(j, open(f"{WORKDIR}/s_{name}.json", "w"))
    print(name, "id=", j.get("id"), "total=", j.get("total"))
    return j

def fetch_pool(name, start=0, end=40, outname=None):
    """Fetch listings for a saved search. Response stores up to 100 hashes,
    price-asc -> [40:100] is the pricier tranche of the same query."""
    s = json.load(open(f"{WORKDIR}/s_{name}.json"))
    qid, hashes = s["id"], s["result"][start:end]
    items = []
    for i in range(0, len(hashes), 10):
        batch = ",".join(hashes[i:i+10])
        j = req(f"https://www.pathofexile.com/api/trade2/fetch/{batch}?query={qid}&realm=poe2")
        items += [x for x in j["result"] if x and not x.get("gone")]
        time.sleep(2.5)
    out = outname or name
    json.dump(items, open(f"{WORKDIR}/pool_{out}.json", "w"))
    print(out, "fetched", len(items))

# ------------------------- parsing -------------------------
def _clean(s):  # "[Spirit|Spirit]" -> "Spirit"
    return re.sub(r'\[([^\[\]|]*\|)?([^\[\]]*)\]', r'\2', s)

MOD_PATTERNS = [  # (regex, key) - extend per task
    (r'\+(\d+) to Spirit', "spirit"), (r'\+(\d+) to maximum Mana', "mana"),
    (r'\+(\d+) to Intelligence', "int"), (r'\+(\d+) to Strength', "str"),
    (r'\+(\d+) to Dexterity', "dex"), (r'\+(\d+) to all Attributes', "allattr"),
    (r'\+(\d+)% to Fire Resistance', "fire"), (r'\+(\d+)% to Cold Resistance', "cold"),
    (r'\+(\d+)% to Lightning Resistance', "light"), (r'\+(\d+)% to Chaos Resistance', "chaos_res"),
    (r'\+(\d+)% to all Elemental Resistances', "allres"),
    (r'(\d+)% increased Movement Speed', "ms"),
]

def parse_item(it, pool):
    item, listing = it["item"], it["listing"]
    mods = []
    for key in ("explicitMods", "implicitMods", "runeMods", "enchantMods",
                "fracturedMods", "desecratedMods", "craftedMods"):
        for m in item.get(key) or []:
            mods.append(_clean(m if isinstance(m, str) else m.get("description", "")))
    d = {k: 0 for _, k in MOD_PATTERNS}
    for s in mods:
        if s.startswith("Bonded:"):  # Shaman-only bonus lines
            continue
        for pat, k in MOD_PATTERNS:
            mm = re.search(pat, s)
            if mm:
                d[k] += int(mm.group(1))
    p = listing.get("price") or {}
    cur, amt = p.get("currency", ""), p.get("amount", 0)
    if cur not in CURRENCY_RATES:
        return None
    es = (item.get("extended") or {}).get("es", 0)
    d.update(fire=d["fire"] + d["allres"], cold=d["cold"] + d["allres"], light=d["light"] + d["allres"])
    attr = d["int"] + d["str"] + d["dex"] + d["allattr"]
    return {"id": item["id"], "pool": pool, "base": item.get("baseType"), "ilvl": item.get("ilvl"),
            "corrupted": item.get("corrupted", False), "es": es, "attr": attr, **d,
            "mana_eq": es + d["mana"] + 2 * attr,   # MOM/EB score (mechanics.md)
            "price": round(amt * CURRENCY_RATES[cur], 3), "cur": f"{amt} {cur}",
            "seller": listing.get("account", {}).get("name", "?"), "mods": mods}

def load_slot(pool_names):
    out, seen = [], set()
    for p in pool_names:
        f = f"{WORKDIR}/pool_{p}.json"
        if not os.path.exists(f):
            continue
        for it in json.load(open(f)):
            c = parse_item(it, p)
            if c and c["id"] not in seen:
                seen.add(c["id"]); out.append(c)
    return out

# ------------------------- optimizer -------------------------
def optimize(slots, budget, constraints, topn=3):
    """slots: dict name -> candidate list. constraints(combo_dict) -> bool.
    Brute-force cross-product; 100^3 is instant, 5 slots may need pre-pruning
    (drop candidates dominated on every axis within the same slot)."""
    names = list(slots)
    results = []
    for combo in itertools.product(*(slots[n] for n in names)):
        p = sum(c["price"] for c in combo)
        if p > budget:
            continue
        agg = {k: sum(c[k] for c in combo) for k in ("fire", "cold", "light", "spirit", "mana_eq")}
        if not constraints(dict(zip(names, combo)), agg):
            continue
        results.append((agg["mana_eq"], p, combo))
    results.sort(key=lambda x: (-x[0], x[1]))
    out, used = [], []
    for r in results:  # keep top-N with mostly-distinct item sets
        ids = {c["id"] for c in r[2]}
        if any(len(ids & u) >= len(ids) - 1 for u in used):
            continue
        out.append(r); used.append(ids)
        if len(out) >= topn:
            break
    return out

if __name__ == "__main__":
    # Example from the 2026-07 MOM/EB task (helm/chest/boots, F42/C29/L13, spirit 73, MS30, 100 div):
    slots = {
        "chest": load_slot(["chest", "chest2", "chest2deep", "chest4"]),
        "boots": [b for b in load_slot(["boots2", "boots3", "boots4", "boots5"]) if b["ms"] >= 30],
        "helm":  load_slot(["helmA", "helmB", "helmC", "helmD", "helm5", "helm6"]),
    }
    def constraints(by_slot, agg):
        return agg["fire"] >= 42 and agg["cold"] >= 29 and agg["light"] >= 13 and agg["spirit"] >= 73
    for budget in (10, 30, 60, 100):
        for score, price, combo in optimize(slots, budget, constraints, topn=1):
            print(f"[{budget}d] mana_eq={score} total={price:.2f}d :: " +
                  " | ".join(f"{c['base']} {c['cur']} @{c['seller']}" for c in combo))
