# -*- coding: utf-8 -*-
"""Multi-slot gear combo optimizer for POE2 trade (多部位配裝聯合求解), 6-slot proven.

Pipeline (knowledge/tricks.md "Probe the ceiling" + "Multi-slot gear combos"):
  0. PROBE FIRST (interactively, before touching this script): price-capped
     high-spec searches per slot, read `total` only — >200 hits = raise the
     stat mins. Cheap-end-only pools make every budget tier collapse to the
     same cheap answer (sampling bias); pool thresholds must come from probes.
  1. Per slot, define searches: high-end pools (at the probed ceiling) + mid
     pools + cheap broad pools. Price asc.
  2. Fetch listings per search (deep-fetch hashes [40:100] = pricier tranche
     of the same query, no extra search POST).
  3. Parse into normalized candidates, staged combine with BOUNDED pruning,
     report best combo per budget tier + top alternatives.

Hard-won API/parsing facts baked in (don't remove casually):
  - full browser UA required (bare "Mozilla/5.0" -> Cloudflare 403)
  - USE A LOGGED-IN POESESSID (read from setting.py). Measured 2026-07-08:
    authenticated (Rules=Account,Ip) and anonymous (Rules=Ip) are SEPARATE
    rate-limit pools. Anonymous fetch has an UNDOCUMENTED hidden quota — the
    visible X-Rate-Limit-Ip-State sits far below cap (~5 of 16) yet a ~600s
    penalty fires around request ~30 with NO rate-limit headers at all; the
    authenticated pool ran 50 back-to-back fetches with zero penalty. So the
    header counters are a lenient decoy and _throttle_wait() CANNOT predict
    the real limiter — logging in is the only thing that fixes bulk fetching.
    (Full data + the debunked VPN-switch idea: knowledge/tricks.md.)
  - _throttle_wait() still honors the visible windows/lockouts (harmless, just
    insufficient alone). 429 backstop sleeps the FULL Retry-After (penalties
    up to ~605s, longer than any published tuple; block ALL trade endpoints).
  - every search + every fetched batch is disk-cached keyed by (name, range)
    -> a killed/crashed run resumes free; delete files to force refresh
  - mod text embeds [A|B] wiki brackets -> strip to B before regex
  - crafted mods live inside explicitMods with flags.crafted
  - "Bonded:" runeMod lines are Shaman-only bonus effects -> excluded
  - current defences come from item.extended (es/ev/ar)
  - RING-ONLY: mana mods scale with "Quality (Mana Modifiers)" catalysts:
    uncorrupted -> value/(1+curQ) * 1.2, floored; corrupted -> as displayed.
    Belts CANNOT take quality (user-corrected 2026-07-08) — displayed = final.
  - CURRENCY_RATES go stale: refresh from poe2scout (knowledge/exchange-rates.md)

Optimizer scaling lessons (learned the hard way at 6 slots / ~1500 candidates):
  - windowed Pareto checks don't scale past ~10k groups, and accumulating
    every feasible combo OOM-kills the process (billions of pairs). Use
    prune_groups() bucket-coarsening hard cap + the bounded heap in the join.
  - keep ALL module-level side effects behind __main__ (an earlier probe
    script imported a sibling module and silently re-ran 13 searches).

Usage: edit CONFIG + SEARCHES + constraints in main(), then run.
  (no args)          searches + fetches (cached) + optimize; uses the POESESSID
                     from setting.py (authenticated pool). If it is missing or
                     expired the script warns and exits — refresh it, or:
  --anon             deliberately run WITHOUT login (anonymous pool). Only for
                     tiny jobs: hits the hidden ~30-request penalty wall.
  --optimize-only    skip network, re-optimize cached pools
Scoring is MOM/EB (mana_eq = ES + mana + 2*attr + 40*incmana%,
knowledge/mechanics.md); swap the mana_eq lines for other builds.
"""
import json, re, time, urllib.request, urllib.error, itertools, os, sys, math, heapq

# Windows consoles default to cp950/cp1252 -> seller names (Korean/CJK) crash
# the final print stage AFTER all the network work is done. Force utf-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ------------------------- CONFIG -------------------------
LEAGUE = "Runes%20of%20Aldur"          # keep URL-encoded; read from setting.py
WORKDIR = "./gear_pools"                # s_*.json / pool_*.json cache dir
CURRENCY_RATES = {"divine": 1.0, "exalted": 1/600.2, "chaos": 1/7.72}  # -> div; REFRESH ME (poe2scout 2026-07-08)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
BUDGET_TIERS = (60, 80, 100, 120)       # div; last tier = the budget
EXCLUDE_IDS = set()                     # item ids sold mid-session -> re-optimize without them
ANON = "--anon" in sys.argv             # opt in to the anonymous pool (see docstring)

def _load_poesessid():
    """Read POESESSID from setting.py (walk up from CWD & this file to find it);
    fall back to the env var. Returns '' if none. setting.py itself just does
    os.getenv('POESESSID',''), so the env is the same source it would use."""
    import importlib.util
    seen = []
    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        d = base
        for _ in range(6):
            if d not in seen:
                seen.append(d)
            d = os.path.dirname(d)
    for c in seen:
        p = os.path.join(c, "setting.py")
        if os.path.isfile(p):
            try:
                spec = importlib.util.spec_from_file_location("_poe_setting", p)
                m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
                if getattr(m, "POESESSID", ""):
                    return m.POESESSID
            except Exception:
                pass
    return os.environ.get("POESESSID", "")

POESESSID = "" if ANON else _load_poesessid()
_auth_checked = False                   # verify the cookie actually authenticated, once
# ----------------------------------------------------------

def _throttle_wait(hdrs):
    """Header-driven throttle (official semantics: developer/docs#ratelimits).
    X-Rate-Limit-<Rule> = max:period:penalty tuples; -State = used:period:locked.
    Returns seconds to wait so the NEXT request stays below every window's cap.
    Limits are dynamic (GGG changes them under load) and frequent violations
    can get access revoked — so obey headers, don't trust fixed intervals."""
    def parse(s):
        return [tuple(int(x) for x in t.split(":")) for t in s.split(",") if t]
    wait = 0
    rules = [r.strip() for r in (hdrs.get("X-Rate-Limit-Rules") or "").split(",") if r.strip()]
    for rule in rules:
        lim, st = hdrs.get(f"X-Rate-Limit-{rule}"), hdrs.get(f"X-Rate-Limit-{rule}-State")
        if not lim or not st:
            continue
        for (mx, per, _pen), (cur, _p2, locked) in zip(parse(lim), parse(st)):
            if locked > 0:
                wait = max(wait, locked + 2)
            elif cur >= mx - 1:          # near cap -> let this window roll over
                wait = max(wait, per)
    return wait

def req(url, data=None):
    global _auth_checked
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if POESESSID:
        headers["Cookie"] = f"POESESSID={POESESSID}"   # authenticated pool (Account,Ip)
    r = urllib.request.Request(url, data=data, headers=headers)
    for _ in range(4):
        try:
            with urllib.request.urlopen(r) as resp:
                out = json.load(resp)
                if POESESSID and not _auth_checked:      # confirm the cookie logged us in
                    _auth_checked = True
                    if "Account" not in (resp.headers.get("X-Rate-Limit-Rules") or ""):
                        print("!! POESESSID from setting.py did NOT authenticate (likely "
                              "expired). Refresh it in setting.py, or rerun with --anon to\n"
                              "   proceed anonymously (hits the hidden ~30-request penalty).",
                              flush=True)
                        sys.exit(2)
                w = _throttle_wait(resp.headers)
                if w:
                    print(f"  rate-limit window near cap -> waiting {w}s", flush=True)
                    time.sleep(w)
                return out
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = int(e.headers.get("Retry-After", "60"))
                print(f"  429 -> sleeping {ra+5}s (penalty blocks ALL trade endpoints)", flush=True)
                time.sleep(ra + 5)
            else:
                raise
    raise RuntimeError("still 429 after retries")

def search(name, query_body):
    f = f"{WORKDIR}/s_{name}.json"
    if os.path.exists(f):
        j = json.load(open(f)); print(name, "cached id=", j.get("id"), "total=", j.get("total"), flush=True)
        return j
    j = req(f"https://www.pathofexile.com/api/trade2/search/poe2/{LEAGUE}",
            json.dumps(query_body).encode("utf-8"))
    json.dump(j, open(f, "w"))
    print(name, "id=", j.get("id"), "total=", j.get("total"), flush=True)
    time.sleep(2)  # burst-guard floor (anti-rapid-click is invisible to headers); 2s pace user-requested 2026-07-08
    return j

def fetch_pool(name, start=0, end=40):
    out_f = f"{WORKDIR}/pool_{name}_{start}_{end}.json"
    if os.path.exists(out_f):
        print(name, f"[{start}:{end}] cached", flush=True); return
    s = json.load(open(f"{WORKDIR}/s_{name}.json"))
    qid, hashes = s["id"], s["result"][start:end]
    items = []
    for i in range(0, len(hashes), 10):
        batch = ",".join(hashes[i:i+10])
        j = req(f"https://www.pathofexile.com/api/trade2/fetch/{batch}?query={qid}&realm=poe2")
        items += [x for x in j["result"] if x and not x.get("gone")]
        time.sleep(1.5)  # burst-guard floor; real fetch cap is the hidden quota (login pool avoids it); 1.5s pace user-requested 2026-07-08
    json.dump(items, open(out_f, "w"))
    print(name, f"[{start}:{end}] fetched", len(items), flush=True)

# ------------------------- query helpers -------------------------
def q(category, stat_filters, extra_filters=None):
    body = {"query": {"status": {"option": "securable"},
                      "stats": [{"type": "and", "filters": stat_filters}],
                      "filters": {"type_filters": {"filters": {"category": {"option": category}}}}},
            "sort": {"price": "asc"}}
    if extra_filters:
        body["query"]["filters"].update(extra_filters)
    return body

SF = lambda sid, mn: {"id": sid, "value": {"min": mn}, "disabled": False}
ES = lambda mn: {"equipment_filters": {"filters": {"es": {"min": mn}}}}
SPIRIT_CHEST = "explicit.stat_3981240776"
SPIRIT_BOOTS = "crafted.stat_3981240776"   # Runes of Aldur boots craft
MS = "explicit.stat_2250533757"
INCMANA = "explicit.stat_2748665614"       # #% increased maximum Mana (rings)
TOT_RES = "pseudo.pseudo_total_elemental_resistance"
TOT_MANA = "pseudo.pseudo_total_mana"
TOT_COLD = "pseudo.pseudo_total_cold_resistance"
TOT_LIGHT = "pseudo.pseudo_total_lightning_resistance"

# Worked example: the 2026-07 six-slot MOM/EB task (F82/C118/L116, Spirit 73,
# MS30, 120 div). value = (query_body, hashes_to_fetch). High-end pool
# thresholds came from ceiling probes — redo the probes for a new task.
SEARCHES = {
    "chestA": (q("armour.chest", [SF(SPIRIT_CHEST, 57)], ES(500)), 100),
    "chestB": (q("armour.chest", [SF(SPIRIT_CHEST, 57)], ES(680)), 40),
    "chestC": (q("armour.chest", [SF(SPIRIT_CHEST, 57), SF(TOT_RES, 60)], ES(450)), 40),
    "chestD": (q("armour.chest", [SF(SPIRIT_CHEST, 57)], ES(780)), 20),
    "chestE": (q("armour.chest", [SF(SPIRIT_CHEST, 60), SF(TOT_RES, 30)], ES(760)), 20),
    "bootsA": (q("armour.boots", [SF(SPIRIT_BOOTS, 12), SF(MS, 30)], ES(150)), 100),
    "bootsB": (q("armour.boots", [SF(SPIRIT_BOOTS, 12), SF(MS, 30), SF(TOT_RES, 60)], ES(100)), 40),
    "bootsC": (q("armour.boots", [SF(SPIRIT_BOOTS, 14), SF(MS, 30)], ES(100)), 40),
    "bootsD": (q("armour.boots", [SF(SPIRIT_BOOTS, 14), SF(MS, 30)], ES(300)), 40),
    "bootsE": (q("armour.boots", [SF(SPIRIT_BOOTS, 15), SF(MS, 30)], ES(250)), 40),
    "bootsF": (q("armour.boots", [SF(SPIRIT_BOOTS, 13), SF(MS, 30), SF(TOT_RES, 100)]), 40),
    "helmA": (q("armour.helmet", [], ES(400)), 100),
    "helmB": (q("armour.helmet", [SF(TOT_RES, 70)], ES(340)), 40),
    "helmC": (q("armour.helmet", [], ES(500)), 40),
    "helmD": (q("armour.helmet", [], ES(600)), 40),
    "helmE": (q("armour.helmet", [SF(TOT_RES, 80)], ES(560)), 40),
    "ringA": (q("accessory.ring", [SF(TOT_RES, 75)]), 100),
    "ringB": (q("accessory.ring", [SF(TOT_COLD, 30), SF(TOT_LIGHT, 30)]), 40),
    "ringC": (q("accessory.ring", [SF(INCMANA, 4), SF(TOT_RES, 40)]), 100),
    "ringD": (q("accessory.ring", [SF(TOT_MANA, 120), SF(TOT_RES, 50)]), 100),
    "ringE": (q("accessory.ring", [SF(INCMANA, 6), SF(TOT_MANA, 175), SF(TOT_RES, 80)]), 100),
    "ringF": (q("accessory.ring", [SF(INCMANA, 6), SF(TOT_MANA, 150), SF(TOT_RES, 100)]), 40),
    # pure-mana rings, NO res requirement (user 2026-07-08: a high-res belt frees
    # ring res budget — the old all-pools-require-res design couldn't cash that in).
    # Probed ceilings ≤120d: inc6+mana270 -> 597, +mana230 -> 2676, +attr40 -> 486.
    "ringG": (q("accessory.ring", [SF(INCMANA, 6), SF(TOT_MANA, 230)]), 100),
    "ringH": (q("accessory.ring", [SF(INCMANA, 6), SF(TOT_MANA, 270)]), 100),
    "ringI": (q("accessory.ring", [SF(INCMANA, 6), SF(TOT_MANA, 230), SF("pseudo.pseudo_total_attributes", 40)]), 40),
    "ringJ": (q("accessory.ring", [SF(INCMANA, 6), SF(TOT_MANA, 170)]), 40),
    "beltA": (q("accessory.belt", [SF(TOT_RES, 85)]), 100),
    "beltB": (q("accessory.belt", [SF(TOT_MANA, 80), SF(TOT_RES, 60)]), 100),
    "beltC": (q("accessory.belt", [SF(TOT_MANA, 120), SF(TOT_RES, 125)]), 40),
    "beltD": (q("accessory.belt", [SF(TOT_RES, 135)]), 40),
    # dual-high belts (probed ≤120d: mana120+res100 -> 249, mana130+res100 -> 6)
    "beltE": (q("accessory.belt", [SF(TOT_MANA, 120), SF(TOT_RES, 100)]), 100),
    "beltF": (q("accessory.belt", [SF(TOT_MANA, 130), SF(TOT_RES, 100)]), 20),
}
SLOT_POOLS = {  # slot -> pool-name prefix set (load_slot matches on these)
    "chest": {"chestA", "chestB", "chestC", "chestD", "chestE"},
    "boots": {"bootsA", "bootsB", "bootsC", "bootsD", "bootsE", "bootsF"},
    "helm":  {"helmA", "helmB", "helmC", "helmD", "helmE"},
    "ring":  {"ringA", "ringB", "ringC", "ringD", "ringE", "ringF", "ringG", "ringH", "ringI", "ringJ"},
    "belt":  {"beltA", "beltB", "beltC", "beltD", "beltE", "beltF"},
}

# ------------------------- parsing -------------------------
def _clean(s):  # "[Spirit|Spirit]" -> "Spirit"
    return re.sub(r'\[([^\[\]|]*\|)?([^\[\]]*)\]', r'\2', s)

MOD_PATTERNS = [  # (regex, key) - extend per task
    (r'\+(\d+) to Spirit', "spirit"), (r'\+(\d+) to maximum Mana', "mana"),
    (r'\+(\d+) to Intelligence', "int"), (r'\+(\d+) to Strength', "str"),
    (r'\+(\d+) to Dexterity', "dex"), (r'\+(\d+) to all Attributes', "allattr"),
    (r'\+(\d+)% to Fire Resistance', "fire"), (r'\+(\d+)% to Cold Resistance', "cold"),
    (r'\+(\d+)% to Lightning Resistance', "light"),
    (r'\+(\d+)% to all Elemental Resistances', "allres"),
    # dual-res desecrated lines ("+#% to X and Chaos Resistances") — chaos part ignored
    (r'\+(\d+)% to Fire and Chaos Resistances', "fire"),
    (r'\+(\d+)% to Cold and Chaos Resistances', "cold"),
    (r'\+(\d+)% to Lightning and Chaos Resistances', "light"),
    (r'(\d+)% increased Movement Speed', "ms"),
    (r'(\d+)% increased maximum Mana', "incmana"),
]

def quality_info(item):
    """-> (quality_pct, type_name) from item.properties; type_name '' = plain quality."""
    for p in item.get("properties") or []:
        name = _clean(p.get("name", "") or "")
        m = re.match(r'Quality\s*(?:\(([^)]*)\))?', name)
        if m:
            vals = p.get("values") or []
            pct = 0
            if vals and vals[0]:
                mm = re.search(r'(\d+)', str(vals[0][0]))
                if mm: pct = int(mm.group(1))
            return pct, (m.group(1) or "")
    return 0, ""

# Which parsed keys an elemental catalyst quality inflates (verified 2026-07-09
# against tier magnitude ranges in fetched listings): the matching single-res
# line, the matching "X and Chaos" dual line (parsed into the same key), AND
# "+#% to all Elemental Resistances". Attribute-type quality exists (boosts all
# attr mods) but is deliberately NOT reverted — user-confirmed it's never worth
# applying, so listings virtually never carry it (mechanics.md).
ELEM_QUALITY_KEYS = {"Fire": {"fire", "allres"}, "Cold": {"cold", "allres"},
                     "Lightning": {"light", "allres"}}

def parse_item(it, pool, slot):
    item, listing = it["item"], it["listing"]
    corrupted = item.get("corrupted", False)
    qpct, qtype = quality_info(item)
    qmana = "Mana" in qtype
    # user rule case "non-mana quality" (2026-07-09): re-catalysting to mana
    # quality wipes an elemental catalyst -> its boosted res lines revert to
    # their 0%-quality raw values. Revert per-line while parsing.
    revert_keys = set()
    if slot == "ring" and not corrupted and qpct and not qmana:
        for elem, keys in ELEM_QUALITY_KEYS.items():
            if elem in qtype:
                revert_keys = keys
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
                v = int(mm.group(1))
                if k in revert_keys:
                    v = math.floor(v / (1 + qpct / 100.0))
                d[k] += v
    p = listing.get("price") or {}
    cur, amt = p.get("currency", ""), p.get("amount", 0)
    if cur not in CURRENCY_RATES:
        return None
    es = (item.get("extended") or {}).get("es", 0)
    d["fire"] += d["allres"]; d["cold"] += d["allres"]; d["light"] += d["allres"]
    attr = d["int"] + d["str"] + d["dex"] + d["allattr"]
    if slot == "ring":  # mana-catalyst quality conversion — RING-ONLY, belts can't take quality (mechanics.md)
        div = 1 + (qpct / 100.0 if qmana else 0)
        if corrupted or (qmana and qpct >= 20):
            # quality locked, or already at/above the +20% we'd catalyst to
            # (observed up to +60% mana quality on uncorrupted rings 2026-07
            # — special crafts exceed the 20 base cap; displayed = final)
            eff_mana, eff_inc = d["mana"], d["incmana"]
        else:          # assume buyer catalysts to Quality (Mana Modifiers) +20%
            eff_mana = math.floor(d["mana"] / div * 1.2)
            eff_inc = math.floor(d["incmana"] / div * 1.2)
        mana_eq = eff_mana + 40 * eff_inc + 2 * attr   # 40 = mana per 1% at ~4000 total
    else:
        eff_mana, eff_inc = d["mana"], d["incmana"]
        mana_eq = es + d["mana"] + 40 * d["incmana"] + 2 * attr
    return {"id": item["id"], "pool": pool, "slot": slot,
            "name": item.get("name") or "", "base": item.get("baseType"),
            "ilvl": item.get("ilvl"), "corrupted": corrupted, "es": es, "attr": attr,
            "spirit": d["spirit"], "fire": d["fire"], "cold": d["cold"], "light": d["light"],
            "ms": d["ms"], "mana": eff_mana, "incmana": eff_inc, "mana_eq": mana_eq,
            "price": round(amt * CURRENCY_RATES[cur], 3), "cur": f"{amt} {cur}",
            "seller": (listing.get("account") or {}).get("name", "?"),
            "whisper": listing.get("whisper", ""), "mods": mods}

def load_slot(slot, pool_prefixes):
    out, seen = [], set(EXCLUDE_IDS)
    for fn in sorted(os.listdir(WORKDIR)):
        if not fn.startswith("pool_"):
            continue
        pool = fn[5:].rsplit("_", 2)[0]
        if pool not in pool_prefixes:
            continue
        for it in json.load(open(os.path.join(WORKDIR, fn))):
            c = parse_item(it, pool, slot)
            if c and c["id"] not in seen:
                seen.add(c["id"]); out.append(c)
    return out

# ------------------------- optimizer -------------------------
def prune(cands, axes):
    """Per-slot: drop strictly-dominated candidates (another is <= price and
    >= on all axes). O(n^2), fine for a few hundred per slot."""
    kept = []
    cands = sorted(cands, key=lambda c: (c["price"], -c["mana_eq"]))
    for c in cands:
        dom = False
        for k in kept:
            if k["price"] <= c["price"] and all(k[a] >= c[a] for a in axes) \
               and (k["price"] < c["price"] or any(k[a] > c[a] for a in axes)):
                dom = True; break
        if not dom:
            kept.append(c)
    return kept

def agg_tuple(items):
    return (round(sum(c["price"] for c in items), 3),
            sum(c["mana_eq"] for c in items),
            sum(c["fire"] for c in items),
            sum(c["cold"] for c in items),
            sum(c["light"] for c in items))

def prune_groups(groups, cap=50000):
    """groups: list of (price, mana_eq, F, C, L, items).
    Hard-cap by keeping the max-mana_eq entry per (price, F, C, L) bucket,
    coarsening granularity until under cap. NEVER use windowed Pareto checks
    or unbounded accumulation here — 6 slots OOM-killed a run that way.

    cap=50000 default from a measured convergence sweep (2026-07, 6-slot case,
    ~1500 candidates): answers converged at 50k (89s) and stayed identical
    through 100k (14min) and 200k (45min, = fully saturated finest bucketing);
    cap 4000 lost 0.6% on one mid budget tier. If answers matter, do the
    doubling test: rerun with 2x cap, stop when nothing changes. Runtime
    scales with the PRODUCT of the two halves' kept counts (join stage)."""
    kept = groups
    pgran, rgran = 0.5, 6
    while len(kept) > cap:
        best = {}
        for g in kept:
            key = (int(g[0] / pgran), g[2] // rgran, g[3] // rgran, g[4] // rgran)
            cur = best.get(key)
            if cur is None or g[1] > cur[1] or (g[1] == cur[1] and g[0] < cur[0]):
                best[key] = g
        kept = list(best.values())
        if pgran >= 64 and rgran >= 30:
            break
        pgran *= 2; rgran = min(rgran + 4, 30)
    kept.sort(key=lambda g: (g[0], -g[1]))
    return kept

def main():
    os.makedirs(WORKDIR, exist_ok=True)
    if "--optimize-only" not in sys.argv:      # network stages need a rate-limit pool
        if not POESESSID and not ANON:
            print("!! No POESESSID in setting.py — anonymous trade access hits an\n"
                  "   UNDOCUMENTED hidden quota (~30 fetches then a ~600s IP penalty;\n"
                  "   see knowledge/tricks.md). The logged-in pool is separate and ran\n"
                  "   50 fetches with zero penalty. Put a fresh POESESSID in setting.py,\n"
                  "   or rerun with --anon to proceed anonymously anyway.", flush=True)
            sys.exit(2)
        print(f"[mode] {'AUTH (setting.py POESESSID)' if POESESSID else 'ANON (--anon)'}", flush=True)
        for name, (body, _n) in SEARCHES.items():
            search(name, body)
        for name, (_body, n) in SEARCHES.items():
            for st in range(0, n, 40):
                fetch_pool(name, st, min(st + 40, n))

    chest = load_slot("chest", SLOT_POOLS["chest"])
    boots = [b for b in load_slot("boots", SLOT_POOLS["boots"]) if b["ms"] >= 30]
    helm  = load_slot("helm", SLOT_POOLS["helm"])
    ring  = load_slot("ring", SLOT_POOLS["ring"])
    belt  = load_slot("belt", SLOT_POOLS["belt"])
    print("pool sizes:", {k: len(v) for k, v in
          [("chest", chest), ("boots", boots), ("helm", helm), ("ring", ring), ("belt", belt)]}, flush=True)

    AX = ["mana_eq", "fire", "cold", "light"]
    chest_p = prune(chest, AX + ["spirit"])
    boots_p = prune(boots, AX + ["spirit"])
    helm_p  = prune(helm, AX)
    ring_p  = prune(ring, AX)
    belt_p  = prune(belt, AX)
    print("pruned:", len(chest_p), len(boots_p), len(helm_p), len(ring_p), len(belt_p), flush=True)

    # stage 1: chest x boots under the joint Spirit constraint, then x helm
    cb = []
    for c, b in itertools.product(chest_p, boots_p):
        if c["spirit"] + b["spirit"] >= 73:
            t = agg_tuple([c, b]); cb.append(t + ((c, b),))
    cb = prune_groups(cb)
    armour = []
    for g in cb:
        for h in helm_p:
            armour.append((round(g[0] + h["price"], 3), g[1] + h["mana_eq"],
                           g[2] + h["fire"], g[3] + h["cold"], g[4] + h["light"],
                           g[5] + (h,)))
    armour = prune_groups(armour)
    print("armour triples kept:", len(armour), flush=True)

    # stage 2: ring pairs (distinct listings) x belt
    rp = []
    for r1, r2 in itertools.combinations(ring_p, 2):
        t = agg_tuple([r1, r2]); rp.append(t + ((r1, r2),))
    rp = prune_groups(rp)
    jew = []
    for g in rp:
        for bl in belt_p:
            jew.append((round(g[0] + bl["price"], 3), g[1] + bl["mana_eq"],
                        g[2] + bl["fire"], g[3] + bl["cold"], g[4] + bl["light"],
                        g[5] + (bl,)))
    jew = prune_groups(jew)
    print("jewelry triples kept:", len(jew), flush=True)

    # stage 3: join under res + budget. Bounded: best-per-tier + top-40 heap,
    # never accumulate all feasible combos (that OOM'd once).
    NEED_F, NEED_C, NEED_L = 82, 118, 116
    tiers = BUDGET_TIERS
    best_per_tier = {t: None for t in tiers}
    heap, counter = [], 0
    jew.sort(key=lambda g: g[0])
    for a in armour:
        rem = tiers[-1] - a[0]
        if rem <= 0: continue
        for g in jew:
            if g[0] > rem: break
            if a[2] + g[2] < NEED_F or a[3] + g[3] < NEED_C or a[4] + g[4] < NEED_L:
                continue
            price, score = a[0] + g[0], a[1] + g[1]
            for t in tiers:
                if price <= t and (best_per_tier[t] is None or score > best_per_tier[t][0]):
                    best_per_tier[t] = (score, price, a[5] + g[5])
            counter += 1
            if len(heap) < 40:
                heapq.heappush(heap, (score, -price, counter, a[5] + g[5]))
            elif score > heap[0][0]:
                heapq.heapreplace(heap, (score, -price, counter, a[5] + g[5]))
    ranked = sorted(((s, -np, c) for s, np, _i, c in heap), key=lambda x: (-x[0], x[1]))
    alts, used = [], []
    for r in ranked:  # top alternatives with mostly-distinct item sets
        ids = {c["id"] for c in r[2]}
        if any(len(ids & u) >= 5 for u in used):
            continue
        alts.append(r); used.append(ids)
        if len(alts) >= 5: break

    def show(tag, entry):
        if not entry:
            print(f"[{tag}] no feasible combo", flush=True); return
        score, price, combo = entry
        agg = {k: sum(c[k] for c in combo) for k in ("fire", "cold", "light", "spirit")}
        print(f"\n[{tag}] mana_eq={score}  total={price:.2f}d  "
              f"F{agg['fire']} C{agg['cold']} L{agg['light']} Spirit{agg['spirit']}", flush=True)
        for c in combo:
            print(f"  {c['slot']:5s} {c['cur']:>14s}  {(c['name']+' '+c['base']).strip()[:44]:44s} "
                  f"es{c['es']:>4} mana{c['mana']:>4} inc{c['incmana']}% attr{c['attr']:>3} "
                  f"F{c['fire']:>2} C{c['cold']:>3} L{c['light']:>3} sp{c['spirit']:>2} "
                  f"{'CORR' if c['corrupted'] else '    '} @{c['seller']} [{c['pool']}]", flush=True)

    for t in tiers:
        show(f"best<={t}d", best_per_tier[t])
    print(f"\n===== top-5 alternatives @{tiers[-1]}d =====", flush=True)
    for i, r in enumerate(alts):
        show(f"alt{i+1}", r)

    ikeys = ("slot", "name", "base", "cur", "price", "seller", "es", "mana", "incmana",
             "attr", "fire", "cold", "light", "spirit", "ms", "corrupted", "mods", "id", "pool")
    json.dump({"tiers": {str(t): (best_per_tier[t][0:2] +
                                  ([{k: c[k] for k in ikeys} for c in best_per_tier[t][2]],))
                         if best_per_tier[t] else None for t in tiers},
               "alts": [(r[0], r[1], [{k: c[k] for k in ikeys} for c in r[2]]) for r in alts]},
              open(os.path.join(WORKDIR, "result.json"), "w"), indent=1)
    print("\nsaved ->", os.path.join(WORKDIR, "result.json"), flush=True)
    print("query ids:", {n: json.load(open(f"{WORKDIR}/s_{n}.json")).get("id") for n in SEARCHES}, flush=True)
    # After picking a winner: verify each listing is still live (single-hash
    # fetch with its pool's query id), build seller-filtered links
    # (trade_filters.account.input), and deliver per knowledge/delivery.md.

if __name__ == "__main__":  # NEVER put searches at module level (import re-runs them)
    main()
