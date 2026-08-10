# -*- coding: utf-8 -*-
"""Multi-slot gear optimizer for POE1 /trade -- LIFE + ENERGY SHIELD objective
with ATTRIBUTE requirements (生命+ES 加權、含屬性硬約束的多部位聯合求解).

!! REALM: POE1 ONLY. Sibling of gear_combo_optimizer_poe1.py (pure-life, 6 slots,
!! 3 constraint axes) and of gear_combo_optimizer_poe2.py (POE2 ONLY). Every
!! endpoint, field name, stat id, currency and mod regex here is a POE1 profile
!! re-derived from ../poe1/QUERY.md + ../poe1/references/stats.tsv. A wrong-game
!! stat id can be SILENTLY VALID and quietly return the wrong items.

WHY A SECOND POE1 SCRIPT instead of a flag on the first one:
  * objective is a WEIGHTED SUM of life and energy shield, not life alone;
  * there are FIVE joint constraints (fire/cold/lightning + strength + dexterity),
    not three -- which kills the 3-D suffix-max join the other script uses;
  * ES has to be read from TWO different places depending on slot (see es_of()).
Merging those into the life-only script would have made both harder to trust.

Built 2026-08-02 on Allflame for: "buy helmet + gloves + 1 ring + belt within
10 divine, cover fire 142 / cold 73 / lightning 112 and dex 41 / str 95, maximise
2.20*life + 2.41*energy_shield".

Pipeline (../common/tricks.md):  probe -> pools -> solve -> verify -> converge -> report

Usage:
    python gear_combo_es_poe1.py selftest     # brute-force check the solver FIRST
    python gear_combo_es_poe1.py probe
    python gear_combo_es_poe1.py pools
    python gear_combo_es_poe1.py deep         # extend pools to 100 without re-searching
    python gear_combo_es_poe1.py reparse      # re-fetch rows whose craft data is stale
    python gear_combo_es_poe1.py negatives    # ASK the user which downsides to ban
    python gear_combo_es_poe1.py solve        # POE_FAST defaults to 280 (~5 min)
    python gear_combo_es_poe1.py converge
    python gear_combo_es_poe1.py report
    POE_FAST=130 python ... solve             # ~1 min, but NOT converged -- see FAST
    POE_FAST=0   python ... solve             # exact -- did NOT finish in hours

Requires numpy. Everything else is stdlib.

MEASURED, do not relearn the hard way:
  * `extended.es` is the QUALITY-20 NORMALISED energy shield, not what the item
    shows right now. Verified 2026-08-02 on four helmets: properties said
    237/211/232/218, extended.es said 284/253/278/262 -- exactly x1.2 each. The
    site's armour_filters.es compares against the SAME normalised number, so
    filter and score agree. We score at Q20 and tell the buyer to apply quality.
  * Jewellery has NO extended.es. Ring/belt energy shield is a GLOBAL flat mod
    ("+42 to maximum Energy Shield") and must be parsed from mod text. Using
    extended.es for them silently scores every ring and belt at 0 ES.
  * Never parse flat-ES mod text on ARMOUR: there the mod is LOCAL and is already
    baked into extended.es. Counting both double-counts. See es_of().
"""
import glob
import itertools
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:
    import numpy as np
except ImportError:
    sys.exit("numpy required. pip install numpy")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# =============================== CONFIG ===============================
LEAGUE = "Allflame"
WORKDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gear_pools_poe1_es")

# --- the request -------------------------------------------------------
DIV = 174.1874               # 1 divine in chaos. REFRESH: poe2scout /api/pc/Leagues
BUDGET = round(10 * DIV, 2)  # 10 divine
NEED_RES = (142, 73, 112)    # (fire, cold, lightning) shortfall to cover
NEED_STR = 95
NEED_DEX = 41
MARGIN = 0                   # user chose exact-on-target (2026-08-02)
W_LIFE, W_ES = 2.20, 2.41    # user's effective-EHP weights
REQ_LVL_MAX = None           # user is 90+, no cap
RARITY = "rare"
N_PER_POOL = 30

TIERS = (30, 60, 120, 250, 500, 900, BUDGET)

# chaos-denominated, poe2scout /api/pc/Leagues/Allflame/SnapshotPairs 2026-08-02.
# 1 div moved 118.38 -> 172.73 in five days; ALWAYS re-fetch, never reuse.
# `mirror` is deliberately absent: a mirror-priced listing is out of budget by
# definition, and an unknown currency is dropped by parse_item().
RATES = {"chaos": 1.0, "divine": DIV, "exalted": 1.2870, "annul": 11.5257,
         "chrome": 1.8137, "gcp": 2.7437, "regret": 0.6169, "vaal": 0.5394,
         "scour": 0.3067, "blessed": 0.1761, "regal": 0.2069, "fusing": 0.0969,
         "alt": 0.1595, "chance": 0.0716, "alch": 0.0752, "jewellers": 0.0189,
         "transmute": 0.0103}

# UA discipline (../common/tricks.md): the ONLY source is .poe_cookies.json, which
# stores the UA the cookie was captured under. A drifting UA gets POESESSID
# revoked. The literal below is a last-resort fallback for a missing file.
_UA_FALLBACK = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

CAT = {"helm": "armour.helmet", "glove": "armour.gloves",
       "ring": "accessory.ring", "belt": "accessory.belt"}
ZH = {"helm": "頭盔", "glove": "手套", "ring": "戒指1", "belt": "腰帶"}
SLOT_ORDER = ["helm", "glove", "ring", "belt"]
# Slots whose energy shield is an ITEM DEFENCE (extended.es) rather than a global
# flat mod. Getting this set wrong silently mis-scores every item in the slot.
ARMOUR_SLOTS = {"helm", "glove"}

# Candidates kept per slot before craft expansion. 0 = exact.
#
# DEFAULT 280. Re-measured 2026-08-10 after the v1/v2 hot-loop work made the
# solver ~5x faster; the old default of 200 was picked when 280 cost 37 minutes.
# Full 7-tier ladder on a ~3150-listing sample, machine idle:
#     130 -> ~60s | 280 -> 296s | 400 -> 726s
# and the 1741.87c headline was 3160 / 3204 / 3204, with the 500c and 900c rungs
# also identical at 280 and 400. So 280 is the first rung that reaches the
# converged headline, and it fits the 20-minute budget four times over.
#
# !! 130 IS NOT CONVERGED any more. It was, before the craft-swap accounting was
# fixed (130/200/280 all returned 3274 on the old, over-credited candidates).
# Correcting the candidate values changed the shape of the ladder -- a reminder
# that the converged rung is a property of the DATA, not of the algorithm, and
# has to be re-derived whenever candidate scoring changes.
#
# Cost grows roughly with |A|x|J|, so it is QUADRATIC in this number: doubling
# the retention is ~4x the wall clock. Exact (0) did not finish in hours.
FAST = int(os.environ.get("POE_FAST", "280"))
CRAFT = int(os.environ.get("POE_CRAFT", "1"))

# Reference point for the ETA print in cmd_solve: |A|*|J| -> seconds. Calibrated
# 2026-08-10 on the post-v2 solver, full 7-tier ladders, machine idle:
#     FAST=280  437,018 x   666,257 groups   296.5s  -> 9.82e11 groups/s
#     FAST=400  510,253 x 1,122,938 groups   725.8s  -> 7.89e11 groups/s
# The model is only roughly linear in |A|x|J|, so the two disagree by ~25%. Take
# the SMALLER rate, which makes the printed ETA the pessimistic one -- this
# number exists to answer "will this fit in my time budget?", and an estimate
# that runs long is the harmless direction to be wrong in.
_ETA_GROUPS_PER_SEC = 7.89e11
# ======================================================================


def _cookie_cache():
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        p = os.path.join(d, ".poe_cookies.json")
        if os.path.isfile(p):
            try:
                return json.load(open(p, encoding="utf-8"))
            except Exception:
                return {}
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return {}


UA = _cookie_cache().get("user_agent") or _UA_FALLBACK


def _load_poesessid():
    import importlib.util
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        p = os.path.join(d, "setting.py")
        if os.path.isfile(p):
            try:
                spec = importlib.util.spec_from_file_location("_poe_setting", p)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                if getattr(m, "POESESSID", ""):
                    return m.POESESSID
            except Exception:
                pass
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return os.environ.get("POESESSID", "")


POESESSID = _load_poesessid()
_auth_ok = None

SEARCH_URL = "https://www.pathofexile.com/api/trade/search/{league}"
FETCH_URL = "https://www.pathofexile.com/api/trade/fetch/{ids}?query={qid}"
RESULT_URL = "https://www.pathofexile.com/trade/search/{league}/{qid}"
FETCH_CAP = 10


# ---------------------- rate limiting -----------------------------------
# MEASURED on /api/trade/fetch (policy `trade-fetch-request-limit`, 2026-08-03):
#   Account  6:4:10
#   Ip       12:4:60, 16:12:60, 100:300:300, 1000:10800:1800
# i.e. the binding rules are 100 per 5 minutes (3.0 s/req sustained) and
# 1000 per 3 HOURS (10.8 s/req sustained). Search is a SEPARATE policy/quota.
#
# The old strategy -- run flat out, then on `cur >= mx-1` sleep the rule's whole
# PERIOD -- is wrong twice over:
#   * throughput: 100 requests at ~2s then a 300s stall is 5.0 s/req effective,
#     worse than simply pacing at 3.1 s/req and never stalling (1.6x slower).
#   * on the 3-hour rule it sleeps `per` = 10800s. Three hours, in one call,
#     looking exactly like a hang. Nearly triggered 2026-08-03 at 788/1000.
# Instead: keep our own timestamps, and before each request sleep only until a
# slot actually frees. Seeded from the server's own counters so a fresh process
# inherits the window a previous one filled.
_RL = {}

# Floor on the gap between two requests, regardless of what the window maths
# says. The site has anti-rapid-click protection (../common/tricks.md): a burst
# that fits every published window can still be treated as hammering and earn a
# 429. User's instruction 2026-08-03.
MIN_INTERVAL = 0.6

# The server-state backstop is KEPT (user's instruction 2026-08-03): eating a
# real 429 costs a penalty (60s on the short IP rules, 300s at 100/5min, 1800s
# at 1000/3h) that dwarfs any wait we impose on ourselves, so it is worth
# over-waiting to avoid one. But sleeping the rule's WHOLE period was
# indefensible -- 10800s on the 3-hour rule. Sleep a tenth of it instead: enough
# to fall clear of the cap, after which the adaptive pacer resumes and holds the
# sustainable rate on its own.
BACKSTOP_FRACTION = 0.10


def _rl_key(url):
    return "fetch" if "/api/trade/fetch/" in url else "search"


def _rl_observe(key, hdrs):
    """Learn the rules, and top up our timestamp log to match the server's count.

    Our log only knows about requests THIS process made; the counters cover the
    whole IP/account. Where the server says more, the difference is back-filled
    as phantom timestamps spread evenly across the window -- so a process that
    starts mid-window paces from the true position instead of bursting into a
    wall it cannot see.
    """
    def parse(s):
        return [tuple(int(x) for x in t.split(":")) for t in (s or "").split(",") if t]
    st = _RL.setdefault(key, {"rules": [], "hits": []})
    rules, counts = [], []
    for rule in [r.strip() for r in (hdrs.get("X-Rate-Limit-Rules") or "").split(",") if r.strip()]:
        lim, state = hdrs.get(f"X-Rate-Limit-{rule}"), hdrs.get(f"X-Rate-Limit-{rule}-State")
        if not lim or not state:
            continue
        for (mx, per, _pen), (cur, _p2, _lk) in zip(parse(lim), parse(state)):
            rules.append((mx, per))
            counts.append((cur, per))
    if rules:
        st["rules"] = rules
    now = time.time()
    # Back-fill BAND BY BAND, shortest window outwards. The windows are nested:
    # "788 in the last 3h" and "51 in the last 5min" together say 737 requests
    # landed between 5min and 3h ago. Spreading all 788 across the whole 3h
    # instead drops ~2.8% of them into the 5-minute window, inflating the count
    # the tight rule is measured against -- measured cost of getting this wrong:
    # a 574s pace where 65s was correct.
    counts.sort(key=lambda cp: cp[1])
    prev_per = prev_cur = 0
    for cur, per in counts:
        want = cur - prev_cur                 # requests inside this band alone
        mine = sum(1 for t in st["hits"] if prev_per <= now - t < per)
        gap, span = want - mine, per - prev_per
        if gap > 0 and span > 0:
            st["hits"].extend(now - (prev_per + span * (i + 0.5) / gap)
                              for i in range(gap))
        prev_per, prev_cur = per, max(prev_cur, cur)
    horizon = max((p for _, p in st["rules"]), default=0)
    st["hits"] = sorted(t for t in st["hits"] if now - t < horizon)


def _rl_pace(key):
    """Sleep just long enough that one more request stays under every window."""
    st = _RL.get(key)
    if not st or not st["rules"]:
        return
    now = time.time()
    horizon = max(p for _, p in st["rules"])
    st["hits"] = hits = sorted(t for t in st["hits"] if now - t < horizon)
    window = 0.0
    for mx, per in st["rules"]:
        recent = [t for t in hits if now - t < per]
        room = mx - 1                      # keep one slot of headroom
        if len(recent) >= room:
            drop = len(recent) - room + 1  # how many must age out
            window = max(window, recent[drop - 1] + per - now)
    # The 0.2s margin covers clock skew against a WINDOW BOUNDARY; it has no
    # business inflating the anti-rapid-click floor, which is an absolute
    # spacing and would otherwise silently become 0.8s.
    if window > 0:
        window += 0.2
    # hits is sorted, so hits[-1] is the most recent request we know about
    floor = (hits[-1] + MIN_INTERVAL - now) if hits else 0.0
    delay = max(window, floor)
    if delay > 0:
        print(f"  pacing {delay:.2f}s (self-tracked, no stall)", flush=True)
        time.sleep(delay)
    _RL[key]["hits"].append(time.time())


def _throttle_wait(hdrs):
    """Backstop on top of _rl_pace(): react to what the SERVER says.

    _rl_pace works from an estimate (it knows request COUNTS from the headers but
    has to guess when those requests happened), so it can be wrong. This catches
    the case where it was wrong in the dangerous direction and we are one slot
    from a cap -- see BACKSTOP_FRACTION for why the sleep is a tenth of the
    period rather than all of it.
    """
    def parse(s):
        return [tuple(int(x) for x in t.split(":")) for t in (s or "").split(",") if t]
    wait = 0
    for rule in [r.strip() for r in (hdrs.get("X-Rate-Limit-Rules") or "").split(",") if r.strip()]:
        lim, st = hdrs.get(f"X-Rate-Limit-{rule}"), hdrs.get(f"X-Rate-Limit-{rule}-State")
        if not lim or not st:
            continue
        for (mx, per, _pen), (cur, _p2, locked) in zip(parse(lim), parse(st)):
            if locked > 0:
                wait = max(wait, locked + 2)
            elif cur >= mx - 1:
                wait = max(wait, per * BACKSTOP_FRACTION)
    return wait


def req(url, data=None):
    global _auth_ok
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if POESESSID:
        headers["Cookie"] = f"POESESSID={POESESSID}"
    r = urllib.request.Request(url, data=data, headers=headers)
    key = _rl_key(url)
    for _ in range(4):
        _rl_pace(key)
        try:
            with urllib.request.urlopen(r) as resp:
                out = json.load(resp)
                if _auth_ok is None:
                    _auth_ok = "Account" in (resp.headers.get("X-Rate-Limit-Rules") or "")
                _rl_observe(key, resp.headers)
                w = _throttle_wait(resp.headers)
                if w:
                    print(f"  server says near cap -> backstop wait {w:.0f}s", flush=True)
                    time.sleep(w)
                return out
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = int(e.headers.get("Retry-After", "60"))
                print(f"  429 -> sleeping {ra+5}s", flush=True)
                time.sleep(ra + 5)
            else:
                raise RuntimeError(f"HTTP {e.code} {url} :: "
                                   f"{e.read().decode('utf-8', 'replace')[:300]}")
    raise RuntimeError("still 429 after retries")


def http_search(name, body, cache=True):
    os.makedirs(WORKDIR, exist_ok=True)
    f = os.path.join(WORKDIR, f"s_{name}.json")
    if cache and os.path.exists(f):
        j = json.load(open(f))
        print(f"{name:26s} cached id={j.get('id')} total={j.get('total')}", flush=True)
        return j
    j = req(SEARCH_URL.format(league=LEAGUE), json.dumps(body).encode("utf-8"))
    json.dump(j, open(f, "w"))
    print(f"{name:26s} id={j.get('id')} total={j.get('total')}", flush=True)
    # pacing handled by _rl_pace() in req(); a fixed sleep here just adds to it
    return j


def http_pool(name, body, need):
    s = http_search(name, body)
    qid, hashes = s["id"], (s.get("result") or [])[:need]
    rows = []
    for i in range(0, len(hashes), FETCH_CAP):
        j = req(FETCH_URL.format(ids=",".join(hashes[i:i + FETCH_CAP]), qid=qid))
        for it in (j.get("result") or []):
            if not it or it.get("gone"):
                continue
            row = parse_item(it, qid, POOL_SLOT.get(name))
            if row:
                rows.append(row)
        # pacing handled by _rl_pace() in req(); a fixed sleep here just adds to it
    return {"qid": qid, "total": s.get("total"), "rows": rows}


# ------------------ transport: in-page fetch (browser) ------------------
# Fallback for a dead POESESSID (../common/tricks.md). Unlike the life-only
# script this one only ships the RAW listing back for local parsing when the pool
# is small; parsing stays in Python so es_of()/MOD_PATTERNS have one definition.
PW_EXE = os.path.expandvars(r"%APPDATA%\npm\playwright-cli.cmd")

_INPAGE_RAW_JS = r"""
async page => await page.evaluate(async () => {
  const LEAGUE = __LEAGUE__, BODY = __BODY__, NEED = __NEED__;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const sr = await fetch('/api/trade/search/' + encodeURIComponent(LEAGUE),
    {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(BODY)});
  if (!sr.ok) return JSON.stringify({error:'search '+sr.status, body:(await sr.text()).slice(0,200)});
  const s = await sr.json();
  const qid = s.id, hashes = (s.result || []).slice(0, NEED);
  await sleep(2000);
  const out = [];
  for (let i = 0; i < hashes.length; i += 10) {
    const fr = await fetch('/api/trade/fetch/' + hashes.slice(i, i+10).join(',') + '?query=' + qid);
    if (fr.status === 429) { await sleep((parseInt(fr.headers.get('Retry-After')||'60')+5)*1000); i -= 10; continue; }
    if (!fr.ok) return JSON.stringify({error:'fetch '+fr.status, qid});
    const j = await fr.json();
    for (const it of (j.result || [])) {
      if (!it || it.gone) continue;
      // keep only the fields parse_item() reads -- whole listings would flood stdout
      const m = it.item;
      out.push({id: it.id, item: {id: m.id, name: m.name, baseType: m.baseType,
        ilvl: m.ilvl, corrupted: m.corrupted, extended: {es: (m.extended||{}).es},
        properties: m.properties, implicitMods: m.implicitMods,
        explicitMods: m.explicitMods, craftedMods: m.craftedMods,
        fracturedMods: m.fracturedMods, enchantMods: m.enchantMods},
        listing: {price: (it.listing||{}).price, account: {name: ((it.listing||{}).account||{}).name}}});
    }
    await sleep(1500);
  }
  return JSON.stringify({qid, total: s.total, raw: out});
})
"""


def _playwright(js, tag="job"):
    os.makedirs(WORKDIR, exist_ok=True)
    f = os.path.join(WORKDIR, f"_{tag}.js")
    with open(f, "w", encoding="utf-8") as fh:
        fh.write(js)
    r = subprocess.run([PW_EXE, "--raw", "run-code", "--filename", f],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900)
    out = (r.stdout or "").strip()
    if not out:
        raise RuntimeError(f"playwright-cli empty stdout; stderr={(r.stderr or '')[:300]}")
    try:
        return json.loads(json.loads(out))
    except Exception:
        raise RuntimeError(f"unparseable playwright output: {out[:300]}")


def browser_pool(name, body, need):
    js = (_INPAGE_RAW_JS.replace("__LEAGUE__", json.dumps(LEAGUE))
                        .replace("__BODY__", json.dumps(body))
                        .replace("__NEED__", str(need)))
    d = _playwright(js, f"pool_{name}")
    if "error" in d:
        raise RuntimeError(f"{name}: {d}")
    rows = [r for r in (parse_item(it, d["qid"], POOL_SLOT.get(name))
                        for it in d.get("raw") or []) if r]
    return {"qid": d["qid"], "total": d.get("total"), "rows": rows}


def transport():
    global _auth_ok
    if os.environ.get("POE_TRANSPORT"):
        return os.environ["POE_TRANSPORT"]
    if not POESESSID:
        return "browser"
    if _auth_ok is None:
        try:
            req(SEARCH_URL.format(league=LEAGUE), json.dumps(
                q("accessory.belt", [SF(TOT_LIFE, 150)])).encode("utf-8"))
        except Exception:
            _auth_ok = False
    return "http" if _auth_ok else "browser"


def run_pool(name, body, need=N_PER_POOL, force=False):
    os.makedirs(WORKDIR, exist_ok=True)
    out_f = os.path.join(WORKDIR, f"parsed_{name}.json")
    if os.path.exists(out_f) and not force:
        d = json.load(open(out_f))
        print(f"{name:26s} cached qid={d.get('qid')} rows={len(d.get('rows', []))}", flush=True)
        return d
    mode = transport()
    d = (http_pool if mode == "http" else browser_pool)(name, body, need)
    json.dump({"name": name, "body": body, **d}, open(out_f, "w"))
    print(f"{name:26s} [{mode}] qid={d['qid']} total={d['total']} rows={len(d['rows'])}",
          flush=True)
    return d


# ------------------------- query builders -------------------------
# Freshly grepped from ../poe1/references/stats.tsv (2026-08-02).
TOT_LIFE = "pseudo.pseudo_total_life"                    # flat life + Strength/2
TOT_RES = "pseudo.pseudo_total_elemental_resistance"
TOT_FIRE = "pseudo.pseudo_total_fire_resistance"
TOT_COLD = "pseudo.pseudo_total_cold_resistance"
TOT_LIGHT = "pseudo.pseudo_total_lightning_resistance"
TOT_ES = "pseudo.pseudo_total_energy_shield"             # +# total maximum ES
TOT_STR = "pseudo.pseudo_total_strength"
TOT_DEX = "pseudo.pseudo_total_dexterity"


def SF(sid, mn):
    return {"id": sid, "value": {"min": mn}, "disabled": False}


def q(category, stat_filters, es_min=None, craftable_only=False, rarity=RARITY):
    """POE1 query body. status/sort at the ROOT, not inside filters.

    es_min goes to armour_filters.es -- that is the item's QUALITY-20 energy
    shield DEFENCE, so it doubles as "this is an ES or ES/AR hybrid base": a pure
    armour/evasion base has no ES value at all and cannot pass es>=1.
    Deliberately NO price cap: the literal-currency cap silently drops listings
    priced in exalted/chrome/alch (../poe1/knowledge/market.md).
    """
    filters = {"type_filters": {"filters": {"category": {"option": category}}}}
    if rarity:
        filters["type_filters"]["filters"]["rarity"] = {"option": rarity}
    if REQ_LVL_MAX:
        filters["req_filters"] = {"filters": {"lvl": {"max": REQ_LVL_MAX}}}
    if es_min is not None:
        filters["armour_filters"] = {"filters": {"es": {"min": es_min}}}
    stats = [{"type": "and", "filters": stat_filters}]
    if craftable_only:
        # count/min:1 == free suffix OR an existing crafted suffix we can wipe.
        # Measured: count groups do NOT hit the complexity limit. crafting.md
        stats.append({"type": "count", "value": {"min": 1}, "filters": [
            {"id": "pseudo.pseudo_number_of_empty_suffix_mods",
             "value": {"min": 1}, "disabled": False},
            {"id": "pseudo.pseudo_number_of_crafted_suffix_mods",
             "value": {"min": 1}, "disabled": False}]})
        filters.setdefault("misc_filters", {"filters": {}})
        filters["misc_filters"]["filters"]["corrupted"] = {"option": "false"}
        # mirrored items are frozen forever -- excluding them at SEARCH time keeps
        # them from eating slots in a pool whose whole point is craftability
        filters["misc_filters"]["filters"]["mirrored"] = {"option": "false"}
    return {"query": {"status": {"option": "securable"},
                      "stats": stats, "filters": filters},
            "sort": {"price": "asc"}}


# ------------------------- parsing -------------------------
# POE1 mod texts. Plain text, no [A|B] wiki brackets, but stripped defensively.
# Crafted mods arrive INSIDE explicitMods (flags.crafted / domain=="crafted").
#
# Attribute bookkeeping, the part that is easy to get wrong:
#   "+42 to Strength and Dexterity" is matched by the bare "to Strength" pattern
#   (substring) so STR needs no hybrid entry -- but DEX does, because
#   "to Dexterity" is NOT a substring of that line. Hence the explicit
#   "Strength and Dexterity" row below. "Dexterity and Intelligence" IS caught by
#   the bare dex pattern. Verify with selftest_parse() after editing.
#
# !! EVERY capture is SIGNED (`[+-]`), never a bare `\+`. Penalties are real and
# they are not rare: the cached snapshot held "-60% to Lightning Resistance" and
# "-58% to Lightning Resistance" listings. A `\+`-anchored pattern reads those as
# ZERO, which OVERSTATES the combo's resistance by up to 60 and produces answers
# that silently miss the requirement. Same hazard for life/ES/attributes.
_SIGNED = r"([+-]\d+)"
MOD_PATTERNS = [
    (_SIGNED + r" to maximum Life", ["life"]),
    (_SIGNED + r" to maximum Energy Shield", ["es_mod"]),
    (_SIGNED + r" to Strength", ["str"]),
    (_SIGNED + r" to Dexterity", ["dex"]),
    (_SIGNED + r" to Strength and Dexterity", ["dex"]),   # str already counted
    (_SIGNED + r" to all Attributes", ["str", "dex"]),
    (_SIGNED + r"% to Fire Resistance", ["fire"]),
    (_SIGNED + r"% to Cold Resistance", ["cold"]),
    (_SIGNED + r"% to Lightning Resistance", ["light"]),
    (_SIGNED + r"% to all Elemental Resistances", ["fire", "cold", "light"]),
    (_SIGNED + r"% to Fire and Cold Resistances", ["fire", "cold"]),
    (_SIGNED + r"% to Fire and Lightning Resistances", ["fire", "light"]),
    (_SIGNED + r"% to Cold and Lightning Resistances", ["cold", "light"]),
    # the chaos half of these is ignored on purpose (chaos res is out of scope)
    (_SIGNED + r"% to Fire and Chaos Resistances", ["fire"]),
    (_SIGNED + r"% to Cold and Chaos Resistances", ["cold"]),
    (_SIGNED + r"% to Lightning and Chaos Resistances", ["light"]),
]
MOD_KEYS = ("life", "es_mod", "str", "dex", "fire", "cold", "light")
AXES = ("life", "es", "fire", "cold", "light", "str", "dex")


def _clean(s):
    return re.sub(r"\[([^\[\]|]*\|)?([^\[\]]*)\]", r"\2", s)


# A mod line starting with a minus sign is a DOWNSIDE -- but "downside" is
# BUILD-SPECIFIC, not universal. "-12 to Evasion Rating" is free for an ES
# character; "-33% to Global Critical Strike Multiplier" is fatal for a crit
# build and irrelevant for an ailment build. So NOTHING is banned by default:
# collect everything, then run the `negatives` subcommand to show the user what
# actually turned up in THIS sample and let them choose. (user 2026-08-02:
# 「並不是所有負面詞都是不可以接受的…可以把幾個可能會影響到流派運作的 pickup 出來詢問」)
NEGATIVE_RE = re.compile(r"^\s*-\d")
# Penalties do not all start with a minus sign. "46% reduced Elemental Damage
# with Attack Skills" is a downside; "20% reduced Enemy Stun Threshold" is an
# upside; "10% reduced Attribute Requirements" is an upside. There is no way to
# tell from the text alone, so these are never auto-classified -- they are
# printed verbatim in the deliverable for the buyer to judge. Found 2026-08-03
# when the winning ring turned out to carry one that nothing had reported.
REDUCED_RE = re.compile(r"\d+% (reduced|less) ")

# Three classes, and only the third needs a human:
#   modelled   -- already a term in MOD_PATTERNS, so its penalty is counted in
#                 the score/constraints numerically. Banning it would be wrong;
#                 a -60% fire res item can still win if it is cheap and the rest
#                 of the set covers the gap.
#   structural -- changes the ITEM's mechanics, not the character's power.
#                 Affix counts feed _suffix_cap(); socket counts are out of scope.
#   unmodelled -- everything else. Effect on the build cannot be inferred from
#                 the objective function, so ASK.
STRUCTURAL_RE = re.compile(r"Modifiers? allowed|to maximum Sockets|"
                           r"Implicit Modifiers Cannot Be Changed")


def _negative_class(text):
    if STRUCTURAL_RE.search(text):
        return "structural"
    for pat, _keys in MOD_PATTERNS:
        if re.search(pat, text):
            return "modelled"
    return "unmodelled"


def _load_banned():
    """Build-specific ban list, chosen by the user after seeing `negatives`.

    Empty by default -- the script must NEVER decide this on its own, and a list
    chosen for one build does not transfer to another (user, 2026-08-02:
    「現在制定的黑名單只適用於這次的我現在這個流派，今後如果有其他流派要配裝的話依然要重新詢問」).
    That is why it lives in WORKDIR next to the pools rather than in this file:
    a new request starts a new WORKDIR and therefore an empty list.
    """
    p = os.path.join(WORKDIR, "banned_mods.json")
    if os.path.isfile(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            return d.get("patterns", []) if isinstance(d, dict) else d
        except Exception:
            pass
    return []


BANNED_MODS = []        # populated in main() once WORKDIR is known
# "+1 Prefix Modifier allowed" / "-2 Suffix Modifiers allowed" -- Reflecting-Mist
# (mirrored) items change how many affixes the item may carry at all.
AFFIX_ALLOWED_RE = re.compile(r"([+-]\d+) (Prefix|Suffix) Modifiers? allowed")
MAX_SUFFIX_DEFAULT = 3          # a normal rare


def _scan_mods(item):
    """-> (totals, crafted_contribution, native_suffix_count, mod_texts, craft_es).

    Minion-only lines are skipped: "Minions have +11% to all Elemental
    Resistances" is a real implicit on Bone Rings and would otherwise be counted
    as if the character got the resistance.

    !! The crafted contribution covers EVERY axis, not just resistance. An item
    may hold only ONE bench craft (../poe1/knowledge/crafting.md), so putting a
    resistance craft on it REMOVES whatever craft is already there -- along with
    all of that mod's stats. Tracking only the crafted RESISTANCE made the solver
    keep a crafted "+13 to Strength and Intelligence" while ALSO adding +35% fire
    to the same slot. Measured 2026-08-03 on Apocalypse Dome Lich's Circlet
    (`of Craft` S0): the delivered combo would have lost 13 strength on crafting
    and landed at 92 against a requirement of 95 -- an answer that does not meet
    the spec, not merely a suboptimal one.

    `craft_es` flags a crafted mod that touches Energy Shield. On ARMOUR slots ES
    is read from extended.es, which already bakes the craft in and cannot be
    un-baked from the listing data, so such items are barred from craft swapping
    rather than mis-valued.
    """
    d = dict.fromkeys(MOD_KEYS, 0)
    craft_all = dict.fromkeys(MOD_KEYS, 0)
    craft_es = False
    affixes, texts = set(), []
    for k in ("implicitMods", "explicitMods", "craftedMods", "fracturedMods", "enchantMods"):
        for m in item.get(k) or []:
            obj = isinstance(m, dict)
            text = _clean(m if not obj else m.get("description", ""))
            texts.append(text)
            if re.search(r"\bMinions?\b|\bAllies\b|\bTotems?\b", text):
                continue
            is_crafted = bool(obj and (m.get("domain") == "crafted"
                                       or (m.get("flags") or {}).get("crafted")))
            if is_crafted and "Energy Shield" in text:
                craft_es = True
            for pat, keys in MOD_PATTERNS:
                mm = re.search(pat, text)
                if mm:
                    val = int(mm.group(1))          # int() handles the sign
                    for key in keys:
                        d[key] += val
                        if is_crafted:
                            craft_all[key] += val
            if obj:
                for sub in (m.get("mods") or []):
                    tier = sub.get("tier") or ""
                    if tier:
                        affixes.add((sub.get("name"), tier, is_crafted))
    native_suffix = len({a for a in affixes if a[1].startswith("S") and not a[2]})
    return d, craft_all, native_suffix, texts, craft_es


def _suffix_cap(texts):
    """How many suffixes this item may hold at all.

    Normally 3. Reflecting-Mist / mirrored items carry implicits that change it
    -- the reference ring had "-2 Suffix Modifiers allowed", so its cap was 1 and
    its single slot was already spent. Assuming a flat 3 made the solver think it
    had two free suffixes and hand it a resistance craft that cannot exist.
    """
    cap = MAX_SUFFIX_DEFAULT
    for t in texts:
        m = AFFIX_ALLOWED_RE.search(t)
        if m and m.group(2) == "Suffix":
            cap += int(m.group(1))
    return max(cap, 0)


def es_of(item, slot, parsed):
    """Energy shield the CHARACTER gains from this item.

    Two different sources, and mixing them up is the single biggest scoring trap
    in this script:
      * ARMOUR (helmet/gloves): extended.es -- the item's ES defence, already
        including its local flat-ES and local %increased-ES mods, normalised to
        20% quality. Parsing the mod text here would DOUBLE COUNT.
      * JEWELLERY (ring/belt): no extended.es at all; the "+# to maximum Energy
        Shield" mods are GLOBAL. Parse them.
    """
    if slot in ARMOUR_SLOTS:
        return int((item.get("extended") or {}).get("es") or 0)
    return int(parsed["es_mod"])


def _prop(item, name):
    for p in item.get("properties") or []:
        if p.get("name") == name:
            try:
                return int(str(p["values"][0][0]).split()[0])
            except Exception:
                return None
    return None


def parse_item(it, qid, slot):
    item, lst = it["item"], it.get("listing") or {}
    d, craft_mod, native_suffix, mods, craft_es = _scan_mods(item)
    p = lst.get("price") or {}
    if p.get("currency") not in RATES:
        return None
    for pat in BANNED_MODS:
        if any(re.search(pat, t) for t in mods):
            return None
    es = es_of(item, slot, d)
    return {"id": item["id"], "qid": qid, "hash": it["id"], "slot": slot,
            "name": f"{item.get('name') or ''} {item.get('baseType') or ''}".strip(),
            "ilvl": item.get("ilvl"), "corrupt": bool(item.get("corrupted")),
            # POE1 marks a MIRRORED item as `duplicated`, NOT `mirrored`.
            # Mirrored items are frozen forever: no bench craft, no anything.
            "mirrored": bool(item.get("duplicated")),
            "suffix_cap": _suffix_cap(mods),
            "negatives": [t for t in mods if NEGATIVE_RE.match(t)],
            # pseudo_total_life convention: flat life + Strength/2
            "life": d["life"] + d["str"] // 2, "flat": d["life"],
            "es": es, "es_now": _prop(item, "Energy Shield"), "es_mod": d["es_mod"],
            "str": d["str"], "dex": d["dex"],
            "fire": d["fire"], "cold": d["cold"], "light": d["light"],
            # full per-axis contribution of the craft already on the item -- it
            # ALL goes away when the resistance craft replaces it. `craft_res` is
            # kept as the resistance-only view for older cached pools.
            "craft_mod": craft_mod, "craft_es": craft_es,
            "craft_res": {k: craft_mod[k] for k in ("fire", "cold", "light")},
            "native_suffix": native_suffix,
            "price": round(p["amount"] * RATES[p["currency"]], 3),
            "raw": f"{p['amount']} {p['currency']}",
            "seller": (lst.get("account") or {}).get("name", "?"), "mods": mods}


def score_of(items):
    """Integer centi-score so numpy can stay in int32. 220*life + 241*es."""
    return sum(round(W_LIFE * 100) * i["life"] + round(W_ES * 100) * i["es"]
               for i in items)


# ------------------------- ceiling probes -------------------------
# Count-only (`total`), no fetch -- cheap on the rate limit. >200 = too soft,
# ~0 = too hard. Grid is ES-first because ES dominates this objective on the
# armour slots (1 ES = 2.41 vs 1 life = 2.20, and ES bases carry 250-500 of it).
PROBE = {
    "helm": [("es", 300, []), ("es", 400, []), ("es", 500, []), ("es", 600, []),
             ("es", 350, [(TOT_RES, 70)]), ("es", 400, [(TOT_RES, 70)]),
             ("es", 450, [(TOT_RES, 70)]), ("es", 400, [(TOT_RES, 100)]),
             ("es", 350, [(TOT_FIRE, 60)]), ("es", 400, [(TOT_LIFE, 80)])],
    "glove": [("es", 150, []), ("es", 200, []), ("es", 250, []), ("es", 300, []),
              ("es", 180, [(TOT_RES, 70)]), ("es", 220, [(TOT_RES, 70)]),
              ("es", 250, [(TOT_RES, 100)]), ("es", 200, [(TOT_FIRE, 60)])],
    "ring": [(None, None, [(TOT_DEX, 41)]),
             (None, None, [(TOT_DEX, 41), (TOT_RES, 80)]),
             (None, None, [(TOT_DEX, 41), (TOT_RES, 110)]),
             (None, None, [(TOT_DEX, 41), (TOT_LIFE, 100), (TOT_RES, 70)]),
             (None, None, [(TOT_DEX, 41), (TOT_LIFE, 120), (TOT_RES, 60)]),
             (None, None, [(TOT_DEX, 41), (TOT_ES, 60)]),
             (None, None, [(TOT_DEX, 41), (TOT_FIRE, 45), (TOT_LIFE, 90)])],
    "belt": [(None, None, [(TOT_STR, 80)]),
             (None, None, [(TOT_STR, 80), (TOT_RES, 70)]),
             (None, None, [(TOT_STR, 80), (TOT_LIFE, 140)]),
             (None, None, [(TOT_STR, 95), (TOT_LIFE, 150)]),
             (None, None, [(TOT_STR, 80), (TOT_ES, 70)]),
             (None, None, [(TOT_LIFE, 170), (TOT_RES, 70)]),
             (None, None, [(TOT_STR, 80), (TOT_FIRE, 45)])],
}


def cmd_probe():
    for slot, rows in PROBE.items():
        for kind, esmin, stats in rows:
            tag = (f"es{esmin}" if esmin else "") + "".join(
                f"_{sid.split('_')[-1][:4]}{v}" for sid, v in stats)
            http_search(f"probe_{slot}_{tag or 'any'}",
                        q(CAT[slot], [SF(s, v) for s, v in stats] or
                          [SF(TOT_LIFE, 1)], es_min=esmin))


# ------------------------- pools -------------------------
# Filled in from the probe counts. POOL_SLOT is derived so parse_item knows which
# ES source to read -- keep every pool name registered here.
POOLS = {}
POOL_SLOT = {}


def define_pools(spec):
    POOLS.clear(); POOL_SLOT.clear()
    for name, v in spec.items():
        POOLS[name] = v
        POOL_SLOT[name] = v[0]


# (slot, [(stat_id, min), ...], es_min, craftable_only)
#
# Thresholds come from the 2026-08-02 probe counts, never guessed. Recorded in
# ../poe1/knowledge/slots.md. Two structural facts drive the shape:
#   * ES is 2.41/point and helmets/gloves carry 250-550 of it, so on those slots
#     the ES filter IS the pool's identity; life and resistance are the trade-off.
#   * The BELT is an either/or: a Crystal Belt's ES implicit (probe: es>=80 has
#     3199 listings) or a Heavy Belt's strength implicit -- str>=80 AND es>=70
#     returned exactly 0. Strength 95 therefore has to be allocated between belt
#     and ring, so both slots get strength-flavoured pools and the solver picks.
POOL_SPEC = {
    # ---- helmet ----  ceiling ~550 (es550 = 3 listings)
    "helm_maxes":    ("helm",  [],                                   500, False),
    "helm_es_res":   ("helm",  [(TOT_RES, 70)],                      500, False),
    "helm_es_res2":  ("helm",  [(TOT_RES, 100)],                     460, False),
    "helm_es_res3":  ("helm",  [(TOT_RES, 130)],                     430, False),
    "helm_es_fire":  ("helm",  [(TOT_FIRE, 60)],                     440, False),
    "helm_es_life":  ("helm",  [(TOT_LIFE, 80)],                     450, False),
    "helm_str":      ("helm",  [(TOT_STR, 40)],                      350, False),
    "helm_craft":    ("helm",  [],                                   480, True),
    "helm_craft2":   ("helm",  [(TOT_RES, 45)],                      440, True),

    # ---- gloves ----  ceiling ~340 (es340 = 16 listings)
    "glove_maxes":   ("glove", [],                                   320, False),
    "glove_es_res":  ("glove", [(TOT_RES, 70)],                      300, False),
    "glove_es_res2": ("glove", [(TOT_RES, 100)],                     280, False),
    "glove_es_res3": ("glove", [(TOT_RES, 130)],                     250, False),
    "glove_es_fire": ("glove", [(TOT_FIRE, 60)],                     260, False),
    "glove_es_life": ("glove", [(TOT_LIFE, 80)],                     270, False),
    "glove_str":     ("glove", [(TOT_STR, 40)],                      200, False),
    "glove_craft":   ("glove", [],                                   290, True),
    "glove_craft2":  ("glove", [(TOT_RES, 45)],                      260, True),

    # ---- ring: the ONLY dexterity source, so every pool demands dex 41 ----
    "ring_res":      ("ring",  [(TOT_DEX, 41), (TOT_RES, 125)],      None, False),
    "ring_life_res": ("ring",  [(TOT_DEX, 41), (TOT_LIFE, 110), (TOT_RES, 90)], None, False),
    "ring_life":     ("ring",  [(TOT_DEX, 41), (TOT_LIFE, 130)],     None, False),
    "ring_es":       ("ring",  [(TOT_DEX, 41), (TOT_ES, 50)],        None, False),
    "ring_str":      ("ring",  [(TOT_DEX, 41), (TOT_STR, 45), (TOT_RES, 70)], None, False),
    "ring_str2":     ("ring",  [(TOT_DEX, 41), (TOT_STR, 45), (TOT_LIFE, 90)], None, False),
    "ring_fire":     ("ring",  [(TOT_DEX, 41), (TOT_FIRE, 45), (TOT_LIFE, 90)], None, False),
    "ring_craft":    ("ring",  [(TOT_DEX, 41), (TOT_LIFE, 100)],     None, True),
    "ring_craft2":   ("ring",  [(TOT_DEX, 41), (TOT_STR, 45)],       None, True),

    # ---- belt: Crystal-Belt-ES branch vs Heavy-Belt-strength branch ----
    "belt_es":       ("belt",  [(TOT_ES, 85), (TOT_RES, 60)],        None, False),
    "belt_es2":      ("belt",  [(TOT_ES, 100)],                      None, False),
    "belt_es_life":  ("belt",  [(TOT_ES, 80), (TOT_LIFE, 140)],      None, False),
    "belt_str":      ("belt",  [(TOT_STR, 100)],                     None, False),
    "belt_str_res":  ("belt",  [(TOT_STR, 95), (TOT_RES, 70)],       None, False),
    "belt_str_life": ("belt",  [(TOT_STR, 85), (TOT_LIFE, 160), (TOT_RES, 60)], None, False),
    "belt_life":     ("belt",  [(TOT_LIFE, 190), (TOT_RES, 70)],     None, False),
    "belt_res":      ("belt",  [(TOT_RES, 125)],                     None, False),
    "belt_craft":    ("belt",  [(TOT_STR, 95)],                      None, True),
    "belt_craft2":   ("belt",  [(TOT_ES, 85)],                       None, True),
    "belt_craft3":   ("belt",  [(TOT_LIFE, 180)],                    None, True),

    # ---- gap fillers (added after round 1) ----
    # Round 1's price histogram showed a hole: the high-ES armour pools started
    # at 600-1200c while the craftable pools topped out at 172-345c, and the
    # optimum was buying right in between. These pools are aimed at that band.
    "helm_es_r100b": ("helm",  [(TOT_RES, 100)],                     410, False),
    "helm_es_r130b": ("helm",  [(TOT_RES, 130)],                     380, False),
    "helm_craft3":   ("helm",  [(TOT_RES, 90)],                      400, True),
    "helm_craft4":   ("helm",  [(TOT_LIFE, 70)],                     430, True),
    "glove_es_r70b": ("glove", [(TOT_RES, 70)],                      260, False),
    "glove_es_r100b": ("glove", [(TOT_RES, 100)],                    240, False),
    "glove_craft3":  ("glove", [(TOT_RES, 90)],                      240, True),
    "glove_craft4":  ("glove", [(TOT_LIFE, 70)],                     250, True),
    "ring_res2":     ("ring",  [(TOT_DEX, 41), (TOT_RES, 105), (TOT_LIFE, 80)], None, False),
    "ring_es2":      ("ring",  [(TOT_DEX, 41), (TOT_ES, 70)],        None, False),
    "belt_es3":      ("belt",  [(TOT_ES, 110), (TOT_RES, 60)],       None, False),
    "belt_es_str":   ("belt",  [(TOT_ES, 90), (TOT_STR, 50)],        None, False),

    # ---- round 2: dexterity is NOT ring-only in POE1 ----
    # Measured 2026-08-02: uncorrupted Lich's Circlet (a pure-ES helmet base)
    # rolls plain "+55 to Dexterity" and "+24 to Strength and Dexterity"; Warlock
    # Gloves reach +59 Dex (178 of our rows). So the ES armour slots can carry the
    # attribute requirement and free the ring's suffixes for resistance. Every
    # ring pool above demands dex>=41, which over-constrains that slot -- these
    # add the dex-free alternative, plus armour pools that lean INTO dex.
    "helm_dex":      ("helm",  [(TOT_DEX, 45)],                      430, False),
    "glove_dex":     ("glove", [(TOT_DEX, 45)],                      260, False),
    "helm_dex_res":  ("helm",  [(TOT_DEX, 40), (TOT_RES, 70)],       400, False),
    "glove_dex_res": ("glove", [(TOT_DEX, 40), (TOT_RES, 70)],       230, False),
    "ring_nd_res":   ("ring",  [(TOT_RES, 130)],                     None, False),
    "ring_nd_liferes": ("ring", [(TOT_LIFE, 130), (TOT_RES, 90)],    None, False),
    "ring_nd_life":  ("ring",  [(TOT_LIFE, 155)],                    None, False),
    "ring_nd_es":    ("ring",  [(TOT_ES, 75)],                       None, False),
    "ring_nd_str":   ("ring",  [(TOT_STR, 60), (TOT_LIFE, 110)],     None, False),
    "ring_nd_craft": ("ring",  [(TOT_LIFE, 130)],                    None, True),
}
define_pools(POOL_SPEC)


def cmd_pools(force=False):
    for name, (slot, stats, es_min, craft) in POOLS.items():
        run_pool(name, q(CAT[slot], [SF(s, v) for s, v in stats] or [SF(TOT_LIFE, 1)],
                         es_min=es_min, craftable_only=craft), force=force)


def cmd_reparse():
    """Re-fetch every cached row by (qid, hash) and re-parse it with the CURRENT
    parser, replacing the stored row.

    Needed because pools keep only the parsed result plus mod TEXT -- which mods
    were bench crafts is not recoverable from the cache, so a parser change that
    depends on that flag (see _scan_mods, 2026-08-03) cannot be applied
    retroactively without going back to the API.

    Doubles as a liveness refresh: rows whose listing is gone are dropped, which
    is exactly what `converge` would otherwise discover one round at a time.
    """
    def stale(r):
        """Needs a round trip? Only if the missing craft data could change its
        value -- i.e. the item could actually carry a bench craft. A corrupted /
        mirrored / suffix-full listing is barred from crafting either way, so its
        cached row is already correct and re-fetching it would spend quota (the
        scarce resource here) to rewrite identical numbers. Measured 2026-08-03:
        186 rows genuinely stale out of 1277 un-reparsed."""
        if craft_known(r):
            return False
        ns = r.get("native_suffix")
        return (ns is not None and not r.get("corrupt") and not r.get("mirrored")
                and ns < r.get("suffix_cap", MAX_SUFFIX_DEFAULT))

    n_fixed = n_gone = n_kept = 0
    for fn in sorted(glob.glob(os.path.join(WORKDIR, "parsed_*.json"))):
        d = json.load(open(fn))
        slot = POOLS.get(d.get("name", ""), (None,))[0]
        if slot is None:
            continue
        rows = d.get("rows", [])
        todo = [r for r in rows if stale(r) and r.get("hash") and r.get("qid")]
        if not todo:
            n_kept += len(rows)
            continue
        by_qid = {}
        for r in todo:
            by_qid.setdefault(r["qid"], []).append(r["hash"])
        replaced, failed = {}, False
        for qid, hashes in by_qid.items():
            for i in range(0, len(hashes), FETCH_CAP):
                try:
                    got = _fetch_hashes(qid, hashes[i:i + FETCH_CAP])
                except Exception as e:
                    print(f"  {d['name']}: fetch failed ({e}); leaving rows stale")
                    failed = True
                    break
                for it in got:
                    if it and not it.get("gone"):
                        row = parse_item(it, qid, slot)
                        if row:
                            replaced[row["id"]] = dict(row, pool=d.get("name"))
            if failed:
                break
        todo_ids = {r["id"] for r in todo}
        out = []
        for r in rows:
            if r["id"] in replaced:
                out.append(replaced[r["id"]])
            elif r["id"] in todo_ids and not failed:
                n_gone += 1            # asked for it, server no longer has it
            else:
                out.append(r)
        n_fixed += len(replaced)
        n_kept += len(out) - len(replaced)
        d["rows"] = out
        json.dump(d, open(fn, "w"))
        print(f"{d['name']:26s} refreshed {len(replaced):>3}, sold {len(todo)-len(replaced):>2}"
              f", kept {len(out)-len(replaced):>3}", flush=True)
    print(f"\nreparse done: {n_fixed} rows refreshed, {n_gone} sold, {n_kept} kept as-is")


def cmd_negatives(top=40):
    """List the negative mods present in the collected sample, classified, so the
    user can decide which ones disqualify a listing for THEIR build.

    Run this AFTER `pools`/`deep` and BEFORE `solve`. Write the chosen patterns to
    <WORKDIR>/banned_mods.json (a JSON list of regexes) and re-run `solve`.
    """
    rows, seen = [], set()
    for fn in glob.glob(os.path.join(WORKDIR, "parsed_*.json")):
        for r in json.load(open(fn))["rows"]:
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r)
    buckets = {"unmodelled": {}, "modelled": {}, "structural": {}}
    for r in rows:
        for t in (r.get("mods") or []):
            if not NEGATIVE_RE.match(t):
                continue
            # collapse the magnitude so "-33%" and "-34%" are one entry
            key = re.sub(r"-\d+(\.\d+)?", "-#", t)
            b = buckets[_negative_class(t)].setdefault(
                key, {"n": 0, "slots": set(), "examples": set()})
            b["n"] += 1
            b["slots"].add(r["slot"])
            b["examples"].add(t)
    print(f"sample: {len(rows)} listings\n")
    for cls, title in (("unmodelled", "需要使用者判斷（效果無法從目標函數推得）"),
                       ("modelled", "已納入評分／約束計算，不需禁（禁了反而會少選項）"),
                       ("structural", "只改物品結構，不影響角色強度")):
        d = buckets[cls]
        print(f"=== {cls.upper()} — {title}  ({len(d)} 種)")
        for key, v in sorted(d.items(), key=lambda kv: -kv[1]["n"])[:top]:
            print(f"  {v['n']:>4} 件  [{'/'.join(sorted(v['slots'])):<16}]  {key}")
        print()
    return buckets


def cmd_deep(upto=100):
    """Extend every cached pool from N_PER_POOL to `upto` listings WITHOUT
    re-searching -- a search response stores a window of up to 100 result hashes
    and results are price-ascending, so hashes [30:100] are the same query's more
    expensive tranche (../common/tricks.md).

    Worth it exactly when the budget BINDS: on this task the good pools were the
    cheap craftable ones (helm_craft2: 355 listings, the cheapest 30 spanned only
    75-345c) while the optimum was buying in the 300-700c band -- i.e. the answer
    was sitting at the edge of what had been sampled.
    """
    for name in POOLS:
        sf = os.path.join(WORKDIR, f"s_{name}.json")
        pf = os.path.join(WORKDIR, f"parsed_{name}.json")
        if not (os.path.exists(sf) and os.path.exists(pf)):
            print(f"{name:26s} skip (run `pools` first)")
            continue
        s, d = json.load(open(sf)), json.load(open(pf))
        have = {r["id"] for r in d["rows"]}
        # Rows can be fewer than the hashes already consumed (sold/gone/unknown
        # currency), so derive the to-do list by DIFFING hashes rather than
        # slicing from len(rows) -- slicing would silently re-fetch or skip.
        done = {r.get("hash") for r in d["rows"]}
        hashes = [h for h in (s.get("result") or [])[:upto] if h not in done]
        if not hashes:
            print(f"{name:26s} already deep ({len(d['rows'])} rows)")
            continue
        added = 0
        for i in range(0, len(hashes), FETCH_CAP):
            if transport() == "http":
                j = req(FETCH_URL.format(ids=",".join(hashes[i:i + FETCH_CAP]),
                                         qid=s["id"]))
                # pacing handled by _rl_pace() in req(); a fixed sleep here just adds to it
            else:
                js = (_HASH_FETCH_JS.replace("__QID__", json.dumps(s["id"]))
                      .replace("__HASHES__", json.dumps(hashes[i:i + FETCH_CAP])))
                j = _playwright(js, "deep")
            for it in (j.get("result") or []):
                if not it or it.get("gone"):
                    continue
                row = parse_item(it, s["id"], POOLS[name][0])
                if row and row["id"] not in have:
                    have.add(row["id"])
                    d["rows"].append(row)
                    added += 1
        json.dump(d, open(pf, "w"))
        ps = [r["price"] for r in d["rows"]]
        print(f"{name:26s} +{added:>3} -> {len(d['rows']):>3} rows  "
              f"price {min(ps):.0f}-{max(ps):.0f}c", flush=True)


# ------------------------- bench crafting -------------------------
# ../poe1/knowledge/crafting.md. One crafted mod per item; resistance crafts are
# suffixes, so the item must be uncorrupted with <=2 native suffixes used. Rolls
# are re-rollable for free, so value them at the tier maximum.
CRAFT_CAPS = {"armour": (35, 20), "jewel": (28, 16)}
CRAFT_CLASS = {"helm": "armour", "glove": "armour", "belt": "armour",
               "ring": "jewel"}


def craft_options(slot):
    single, dual = CRAFT_CAPS[CRAFT_CLASS[slot]]
    return [(f"火+{single}", (single, 0, 0)), (f"冰+{single}", (0, single, 0)),
            (f"雷+{single}", (0, 0, single)), (f"火冰+{dual}", (dual, dual, 0)),
            (f"火雷+{dual}", (dual, 0, dual)), (f"冰雷+{dual}", (0, dual, dual))]


def craft_known(c):
    """Was this row parsed by a build that records the FULL crafted contribution?

    Rows cached before 2026-08-03 only stored the crafted resistance, so a
    non-resistance craft on them is invisible and applying a resistance craft
    would over-credit the item (see _scan_mods). Such rows are barred from craft
    expansion rather than trusted -- re-run `reparse` to make them usable again.
    """
    return isinstance(c.get("craft_mod"), dict)


def has_free_suffix(c):
    """Can a resistance suffix still be bench-crafted onto this listing?

    Three blockers, all measured 2026-08-02:
      * corrupted  -- the long-known one.
      * MIRRORED (`duplicated` in the API) -- a mirrored item is permanently
        frozen; no craft of any kind. Missing this check made the solver credit a
        mirrored ring with a +28 fire craft that can never be applied, and the
        combo it produced was 28 fire short of the requirement.
      * suffix slots already full -- and the cap is NOT always 3: Reflecting-Mist
        items carry "-2 Suffix Modifiers allowed" style implicits (see
        _suffix_cap). An existing CRAFTED suffix is reclaimable so it doesn't
        count; only native ones do.
    Pools cached before these fields existed lack them -> treated as not craftable.
    """
    ns = c.get("native_suffix")
    if ns is None or c.get("corrupt") or c.get("mirrored"):
        return False
    if not craft_known(c):
        return False
    # An ES-touching craft on an armour piece is already inside extended.es and
    # cannot be subtracted back out of it, so swapping it away would leave the
    # score overstated by an unknown amount. Refuse rather than guess.
    if c.get("craft_es") and c["slot"] in ARMOUR_SLOTS:
        return False
    return ns < c.get("suffix_cap", MAX_SUFFIX_DEFAULT)


def craftable(c):
    return bool(CRAFT) and has_free_suffix(c)


def craft_potential(c):
    return 1 if (has_free_suffix(c) and not c.get("craft")) else 0


def expand_crafts(cands):
    """Add one virtual candidate per resistance craft the item could carry.

    Applying a craft REPLACES any craft already on the item, so every axis that
    craft contributed has to come back off first -- not just resistance. Life is
    recomputed rather than adjusted, because pseudo_total_life folds in
    Strength//2 and integer division does not distribute over subtraction.
    """
    out = []
    for c in cands:
        out.append(dict(c, craft=None))
        if not craftable(c):
            continue
        cm = c.get("craft_mod") or {}
        flat = c["flat"] - cm.get("life", 0)
        st, dx = c["str"] - cm.get("str", 0), c["dex"] - cm.get("dex", 0)
        # armour ES lives in extended.es and craftable() already refused any item
        # whose existing craft touched it, so only jewellery needs the subtraction
        es = c["es"] if c["slot"] in ARMOUR_SLOTS else c["es"] - cm.get("es_mod", 0)
        base = (c["fire"] - cm.get("fire", 0), c["cold"] - cm.get("cold", 0),
                c["light"] - cm.get("light", 0))
        for label, (df, dc, dl) in craft_options(c["slot"]):
            out.append(dict(c, fire=base[0] + df, cold=base[1] + dc,
                            light=base[2] + dl, craft=label,
                            flat=flat, str=st, dex=dx, es=es,
                            life=flat + st // 2))
    return out


# ------------------------- candidate prep -------------------------
_SOLD = "sold.json"


def tkey(b):
    return f"{float(b):g}"


def sold_ids():
    p = os.path.join(WORKDIR, _SOLD)
    return set(json.load(open(p))) if os.path.exists(p) else set()


def add_sold(ids):
    p = os.path.join(WORKDIR, _SOLD)
    cur = sold_ids() | set(ids)
    json.dump(sorted(cur), open(p, "w"))
    return cur


def load():
    excl = sold_ids()
    by_slot = {s: {} for s in CAT}
    for fn in sorted(glob.glob(os.path.join(WORKDIR, "parsed_*.json"))):
        d = json.load(open(fn))
        slot = POOLS.get(d.get("name", ""), (None,))[0]
        if slot is None:
            continue
        for r in d.get("rows", []):
            if r["id"] in excl or r["price"] > BUDGET:
                continue
            # Re-apply the ban list here as well as in parse_item(): pools cached
            # BEFORE the user chose their bans were parsed without them, and
            # re-fetching just to drop a handful of rows would be wasteful.
            if BANNED_MODS and any(re.search(p, t) for p in BANNED_MODS
                                   for t in (r.get("mods") or [])):
                continue
            r = dict(r, pool=d["name"], slot=slot)
            old = by_slot[slot].get(r["id"])
            if old is None or r["price"] < old["price"]:
                by_slot[slot][r["id"]] = r
    return {k: list(v.values()) for k, v in by_slot.items()}


def pareto(cands):
    """Drop a candidate if another is at most as expensive and at least as good
    on EVERY axis (life, es, 3 res, str, dex) plus craft potential."""
    out = []
    for c in sorted(cands, key=lambda c: (c["price"], -score_of([c]))):
        if not any(all(k[a] >= c[a] for a in AXES)
                   and craft_potential(k) >= craft_potential(c)
                   and k["price"] <= c["price"] for k in out):
            out.append(c)
    return out


def thin(cands, k):
    """Keep the EXTREMES of every axis the optimizer trades off, not the top-k of
    one ranking (that would throw away exactly the pieces a constraint needs)."""
    if len(cands) <= k:
        return cands
    n = max(4, k // 6)
    keep, seen = [], set()
    rankings = [lambda c: -score_of([c]),
                lambda c: -c["es"], lambda c: -c["life"],
                lambda c: -c["fire"], lambda c: -c["cold"], lambda c: -c["light"],
                lambda c: -c["str"], lambda c: -c["dex"],
                lambda c: -(c["fire"] + c["cold"] + c["light"]),
                lambda c: -score_of([c]) / max(c["price"], 0.5),
                lambda c: (c["price"], -score_of([c])),
                lambda c: (-craft_potential(c), -score_of([c])),
                lambda c: (-craft_potential(c), c["price"])]
    for key in rankings:
        for c in sorted(cands, key=key)[:n]:
            if c["id"] not in seen:
                seen.add(c["id"])
                keep.append(c)
    return keep


def prep(pools):
    """pareto -> thin on PHYSICAL listings, THEN expand craft options.

    Order matters (measured on the life-only task): expanding first makes ~7
    virtual candidates per listing and eats thin()'s budget with variants of a
    few items instead of a diverse set -- it scored BELOW the no-craft run, which
    is impossible on the merits. See ../poe1/knowledge/crafting.md.
    """
    p = {k: pareto(v) for k, v in pools.items()}
    if FAST:
        p = {k: thin(v, FAST) for k, v in p.items()}
    return {k: pareto(expand_crafts(v)) for k, v in p.items()}


# ------------------------- optimizer -------------------------
# Pick one listing per slot maximising 220*life + 241*es subject to five joint
# minimums (fire/cold/lightning/str/dex) and a total price cap.
#
# The life-only sibling joins its two halves through a 3-D suffix-max table. That
# does not survive two extra constraint axes: the table would be
# 143*74*113*96*42 cells. Instead:
#   1. CLAMP every aggregate at the requirement on all five axes. Surplus is
#      worth nothing, so the state space is finite and small.
#   2. Per clamped state keep only the price/score PARETO frontier. Lossless --
#      a query only ever asks "best score at >= X, price <= Y".
#   3. Join the two halves by a VECTORISED scan: for each A aggregate, one numpy
#      mask over all J aggregates. With 4 slots the halves stay small enough that
#      this beats building any table, and it is obviously correct.
# selftest() cross-checks the whole thing against a 4-nested-loop brute force.
PRICE_BIN = 1.0     # chaos. Aggregates are deduped per this bucket; at a 1727c
                    # budget a 0.05c bucket (the life-only script's) would make
                    # dedup useless. Bucketing only merges near-equal prices, it
                    # never relaxes the real per-combo price used downstream.


def clamp_key(f, c, l, s, d, cap):
    return (min(f, cap[0]), min(c, cap[1]), min(l, cap[2]),
            min(s, cap[3]), min(d, cap[4]))


# !! The clamp ceiling is NOT `need`. Clamping at `need` is only sound while every
# aggregate is non-negative, and POE1 listings carry real penalties
# ("-60% to Lightning Resistance", "-92% to Cold Resistance" on a ring). Once one
# half goes negative on an axis, the OTHER half must supply MORE than `need` to
# compensate -- but it too was clamped at `need`, so it can never express the
# surplus and the (feasible, often optimal) combo is silently dropped.
#
# Caught by selftest 2026-08-02: brute force 314602, solver 293722 -- the solver
# skipped its own best A aggregate because a negative-resistance item made
# `deficit` exceed what any clamped J entry could show. The direction is safe
# (never returns an infeasible combo) but it is a WRONG ANSWER, not just a lossy
# one, and it hits the exact solver too.
#
# Fix: when clamping a partial aggregate over a set S of slots, the ceiling is
#   cap[S][axis] = need[axis] - sum(min achievable value over slots NOT in S)
# so the partial can always represent enough surplus to cover however negative
# the remaining slots might go. Soundness of the INTERMEDIATE clamp (stage 1 of a
# half, before stage 2's slot is added) follows from cap_stage1 = cap_stage2 -
# m_stage2slot: for any glove value gv >= m_glove, capH + gv >= capA, so an
# already-capped stage-1 value still clamps to exactly capA at stage 2.
#
# Cost is near zero in practice: the ceiling only rises on axes where some slot
# rolls negative, and it rises on the OPPOSITE half -- e.g. the ring's -92 cold
# lifts the helm+glove ceiling to 165 cold, a level helm+glove cannot reach
# anyway, so no extra states become reachable.
def slot_minima(cands):
    """Per-axis minimum an aggregate of this slot can contribute."""
    if not cands:
        return (0, 0, 0, 0, 0)
    return tuple(min(c[a] for c in cands)
                 for a in ("fire", "cold", "light", "str", "dex"))


def _cap(need, *others):
    """need + how negative the slots NOT yet folded in could go, per axis.

    Each remaining slot contributes max(0, -min) -- its own negative reach only.
    Two properties this formula must keep, both learned by breaking them:

      * cap >= need, ALWAYS. A tighter ceiling (subtracting a POSITIVE minimum)
        looks like a free optimization and is not: solve() derives its per-axis
        deficit as `need - ak`, which assumes ak was never clamped below the true
        value. Clamping below need overstates the deficit and the solver returns
        None on a feasible problem. Measured: selftest went from a 293722-vs-
        314602 understatement to finding nothing at all.
      * summing each slot's NEGATIVE reach separately, not the reach of their sum.
        A glove that can go -13 and a ring that always gives +20 must still lift
        the ceiling by 13; netting them to 0 makes the intermediate clamp lossy
        again (min(min(h,cap)+gv, cap) != min(h+gv, cap) when gv < 0).
    """
    return tuple(need[i] + sum(max(0, -o[i]) for o in others) for i in range(5))


def frontier(groups):
    """Per clamped state keep only the price/score Pareto frontier.

    !! The running maximum starts at None, NOT at -1. Scores go NEGATIVE: a ring
    carrying "-131 to maximum Life" scores 220*-131 = -28820, and against a -1
    sentinel `score > best` is false on the very first entry, so the whole state
    is discarded. Measured 2026-08-03 (selftest seed 10): that ring was the only
    aggregate in its state, J could not express the state at all, and solve()
    returned None on a problem brute force solved at 212532.

    Third instance of the same root cause as the clamp ceiling and the deficit
    shortcut -- an unstated "everything is non-negative" assumption that was true
    until the mod parser started reading penalties correctly. When a value's
    RANGE changes, every sentinel, clamp and early-exit downstream needs
    re-deriving, not just the arithmetic.
    """
    by_key = {}
    for g in groups:
        by_key.setdefault(g[2], []).append(g)
    out = []
    for lst in by_key.values():
        lst.sort(key=lambda g: (g[0], -g[1]))
        best = None
        for g in lst:
            if best is None or g[1] > best:
                best = g[1]
                out.append(g)
    return out


def combine(left, right, cap):
    """left x right -> clamped aggregates. Group = (price, score, state, items).

    `cap` is the per-axis clamp ceiling for the slot set AFTER folding in `right`
    -- see the note above clamp_key. Passing `need` here is the bug that selftest
    caught; it is only correct when nothing can go negative.
    """
    best = {}
    for lp, ls, lk, litems in left:
        for c in right:
            p = round(lp + c["price"], 3)
            if p > BUDGET:
                continue
            k = clamp_key(lk[0] + c["fire"], lk[1] + c["cold"], lk[2] + c["light"],
                          lk[3] + c["str"], lk[4] + c["dex"], cap)
            sc = ls + round(W_LIFE * 100) * c["life"] + round(W_ES * 100) * c["es"]
            dk = (k, int(p / PRICE_BIN))
            cur = best.get(dk)
            if cur is None or sc > cur[1] or (sc == cur[1] and p < cur[0]):
                best[dk] = (p, sc, k, litems + (c,))
    return frontier(list(best.values()))


def build_halves(p, need):
    zero = [(0.0, 0, (0, 0, 0, 0, 0), ())]
    mH, mG = slot_minima(p["helm"]), slot_minima(p["glove"])
    mR, mB = slot_minima(p["ring"]), slot_minima(p["belt"])
    # ceiling per stage = need - (minima of the slots still to come, in EITHER half)
    capH = _cap(need, mG, mR, mB)      # helm alone
    capA = _cap(need, mR, mB)          # helm + glove
    capR = _cap(need, mH, mG, mB)      # ring alone
    capJ = _cap(need, mH, mG)          # ring + belt
    A = combine(combine(zero, p["helm"], capH), p["glove"], capA)
    J = combine(combine(zero, p["ring"], capR), p["belt"], capJ)
    return A, J


def _arrays(G):
    return (np.array([g[0] for g in G]),
            np.array([g[1] for g in G], dtype=np.int64),
            np.array([[*g[2]] for g in G], dtype=np.int32))


def _axis_major(k):
    """(N,5) row-major states -> (5,N) axis-major, narrowed to int16 when it fits.

    Both halves of this matter, and both were measured on the real 201605-row J
    (2026-08-10, i7-4790, 8 MB L3):

    * LAYOUT. The mask compares ONE axis at a time, but `k[:, axis]` on a (N,5)
      C-contiguous array walks memory with a 20-byte stride. The CPU always
      fetches a full 64-byte cache line, so ~52 of every 64 bytes pulled in are
      discarded. Storing each axis contiguously makes the scan sequential:
      1.019 ms -> 0.371 ms per mask, a 2.75x win for a transpose.
    * WIDTH. States are clamped resistances and attributes -- the real range is
      about -95..154, and the ceiling is bounded by `need` plus slot slack, so a
      few hundred at most. int32 wastes half the traffic: -> 0.261 ms (3.90x).

    Working set matters as much as speed here: jk shrinks 4.0 MB -> 2.0 MB, which
    is the difference between the hot data fitting in L3 or not. Measured
    side-effect: with a memory-hungry process running alongside, the old layout
    slowed 1.60-2.88x while this one slows only 1.20-1.48x.

    The dtype is chosen from the data rather than hardcoded, so a future
    requirement vector that somehow exceeds int16 degrades to int32 instead of
    silently wrapping around.
    """
    lo, hi = int(k.min()), int(k.max())
    dtype = np.int16 if np.iinfo(np.int16).min < lo and hi < np.iinfo(np.int16).max else np.int32
    return np.ascontiguousarray(k.T, dtype=dtype)


def solve(A, J, budget, need):
    """max score over A x J meeting `need` within `budget`. Exact for the given
    candidate sets."""
    if not A or not J:
        return None
    ap, asc, ak = _arrays(A)
    jp, jsc, jk = _arrays(J)
    # NOTE: J is deliberately NOT sorted. An earlier version sorted jp/jsc/jk by
    # price and then returned J[k] using the SORTED index -- silently handing back
    # a different listing than the one that satisfied the mask (selftest caught it
    # as "cold short 0<18"). The vectorised scan needs no ordering; if you ever
    # reintroduce a sort, map the winning index back through argsort first.
    needv = np.array(need, dtype=np.int32)
    jmaxp = float(jp.max())

    # Two upper bounds, both exact, so the pruning below never changes the answer:
    #  * jscmax    -- best J score at ANY price. Walk A best-score-first and once
    #                 asc[i] + jscmax can no longer beat `best`, no later A can
    #                 either (asc is descending), so BREAK.
    #  * jbest(rem) -- best J score AFFORDABLE with the budget A leaves over,
    #                 from a price-sorted running maximum. Much tighter, and it
    #                 lets us CONTINUE past a row without paying for the 5-axis
    #                 numpy mask over all of J. This is what makes the exact run
    #                 finish: on the real task A=527k and J=2.6M, so the mask is
    #                 ~10ms and doing it 527k times is hours -- the cheap bound
    #                 rejects almost every row for the price of one binary search.
    jscmax = int(jsc.max())
    # Per-axis floor of J. Used to skip an axis mask ONLY when it is provably
    # always satisfied. The old test was `if deficit[axis] > 0`, i.e. "A already
    # covers this axis, so J cannot hurt" -- false, because J can be NEGATIVE.
    # Measured 2026-08-02: that shortcut returned a combo with cold -24 against a
    # requirement of 33 (a ring carrying -68% cold, A covering +44). Unlike the
    # clamp bug this one fails UNSAFE: the answer misses the requirement.
    jkmin = jk.min(axis=0)
    jkT = _axis_major(jk)            # axis-major, int16 -- see _axis_major()
    jsc_argmax = int(np.argmax(jsc))  # fast path when nothing constrains J
    # Exact "how many J rows have axis >= v" tables, one per axis.
    #
    # Knowing the count BEFORE touching J is what lets the axes be tried
    # selectivity-first, and lets a hopeless row be dropped without any scan at
    # all. The point of doing it as a lookup table rather than a sorted copy is
    # SIZE. Two rejected alternatives, both measured 2026-08-10 against v1's 58s:
    #   * argsort indices per axis (+4 MB): 89s. Those indices come out ordered
    #     by VALUE, so every later `jkT[axis][cand]` gather jumps randomly around
    #     a 400 KB array; nonzero() yields ascending indices that stream.
    #   * sorted values per axis for binary search (+2 MB): 107s. No indexing
    #     problem, but 2 MB was enough on its own to push the working set from
    #     5.4 MB back over this CPU's 8 MB L3 -- the cliff is that sharp.
    # State values are small clamped integers, so an exact suffix-count table
    # spans only the axis's own range: about 6 KB for all five, O(1) to query.
    ge_lo, ge_tab = [], []
    for a in range(5):
        row = jkT[a]
        lo, hi = int(row.min()), int(row.max())
        cnt = np.bincount((row - lo).astype(np.int64), minlength=hi - lo + 1)
        ge_lo.append(lo)
        # ge[v - lo] = number of rows with value >= v
        ge_tab.append(np.cumsum(cnt[::-1])[::-1].astype(np.int64).copy())

    def _count_ge(a, d):
        off = d - ge_lo[a]
        if off <= 0:
            return jp.size
        tab = ge_tab[a]
        return int(tab[off]) if off < tab.size else 0
    porder = np.argsort(jp, kind="stable")
    jp_sorted = jp[porder]
    jsc_prefmax = np.maximum.accumulate(jsc[porder])
    best = None
    for i in np.argsort(-asc, kind="stable"):
        if ap[i] > budget:
            continue
        # strict '<' so equal-score-but-cheaper combos are still reachable --
        # summarize()/the tie-break below prefer the cheaper one
        if best is not None and int(asc[i]) + jscmax < best[0]:
            break
        rem = budget - ap[i]
        if best is not None:
            aff = np.searchsorted(jp_sorted, rem + 1e-9, side="right") - 1
            if aff < 0 or int(asc[i]) + int(jsc_prefmax[aff]) < best[0]:
                continue
        deficit = needv - ak[i]
        # Narrow an INDEX SET axis by axis instead of building five full-length
        # boolean masks and ANDing them. Each axis after the first only touches
        # what survived, and an axis that empties the set bails out immediately
        # -- the common case: 41342 of 159277 masks came back empty.
        #
        # A table lookup per constrained axis says how many J rows it admits,
        # without touching J. Two things fall out of knowing that up front:
        #   * if any axis admits ZERO, skip the row without scanning anything;
        #   * the axes can be tried SELECTIVITY FIRST, so the one full scan runs
        #     on the tightest constraint and every later shrink starts from the
        #     smallest possible set. Fixed order could lead with an axis that
        #     rules almost nothing out and hand the rest a huge array to chew.
        # The scan itself stays nonzero(), whose output is ascending -- see the
        # note on axis_val for why value-ordered indices are a trap.
        constrained = []
        for axis in range(5):
            if deficit[axis] <= jkmin[axis]:
                continue                      # provably satisfied by every J
            constrained.append((_count_ge(axis, int(deficit[axis])), axis))
        cand = None
        if constrained:
            constrained.sort()                # fewest survivors first
            if constrained[0][0] == 0:
                continue                      # some axis admits nothing at all
            for n, (_cnt, axis) in enumerate(constrained):
                row = jkT[axis]
                cand = (np.nonzero(row >= deficit[axis])[0] if n == 0
                        else cand[row[cand] >= deficit[axis]])
                if cand.size == 0:
                    break
            if cand.size == 0:
                continue
        if cand is None:
            # nothing constrains J at all
            if rem >= jmaxp:
                k = jsc_argmax
                tot = int(asc[i]) + int(jsc[k])
                if best is None or tot > best[0] or (tot == best[0]
                                                     and ap[i] + jp[k] < best[3]):
                    best = (tot, int(i), int(k), float(ap[i] + jp[k]))
                continue
            cand = np.arange(jp.size)
        # price is filtered LAST, on the narrowed set, and stays float64 so the
        # 1e-9 tolerance keeps the meaning it has everywhere else in this file
        # (in float32 that epsilon is far below the representable step at 1700c
        # and would silently drop listings priced exactly at the remainder)
        if rem < jmaxp:
            cand = cand[jp[cand] <= rem + 1e-9]
            if cand.size == 0:
                continue
        k = cand[int(np.argmax(jsc[cand]))]
        tot = int(asc[i]) + int(jsc[k])
        if best is None or tot > best[0] or (tot == best[0]
                                             and ap[i] + jp[k] < best[3]):
            best = (tot, int(i), int(k), float(ap[i] + jp[k]))
    if best is None:
        return None
    return A[best[1]], J[best[2]]


def summarize(a, j):
    items = list(a[3]) + list(j[3])
    tot = {k: sum(i[k] for i in items) for k in AXES}
    return {"score": round(score_of(items) / 100.0, 2),
            "life": tot["life"], "es": tot["es"],
            "price": round(sum(i["price"] for i in items), 3),
            "res": tot, "items": items}


def needs(margin=None):
    margin = MARGIN if margin is None else margin
    return (NEED_RES[0] + margin, NEED_RES[1] + margin, NEED_RES[2] + margin,
            NEED_STR, NEED_DEX)


def cmd_solve(margin=None, tiers=None, quiet=False):
    need = needs(margin)
    p = prep(load())
    if not quiet:
        print(f"need F{need[0]} C{need[1]} L{need[2]} STR{need[3]} DEX{need[4]}"
              f"{'  FAST=' + str(FAST) if FAST else '  EXACT'}  craft={CRAFT}")
        print("candidates:", {k: len(v) for k, v in p.items()}, flush=True)
    t0 = time.time()
    A, J = build_halves(p, need)
    if not quiet:
        eta = len(A) * len(J) / _ETA_GROUPS_PER_SEC
        print(f"groups A={len(A)} J={len(J)}  ({time.time()-t0:.1f}s)", flush=True)
        # Rough, but it is the number that decides whether to sit and wait or to
        # drop POE_FAST -- and it is available BEFORE the expensive part starts.
        print(f"ETA for all {len(tiers or TIERS)} tiers: ~{eta/60:.0f} min"
              + ("  ⚠ 超過 20 分鐘目標，考慮降低 POE_FAST" if eta > 1200 else ""),
              flush=True)
    out = {}
    # POE_RESULT lets several solves run CONCURRENTLY without racing on one file
    # -- the convergence ladder (FAST=200 vs 280) is two independent single-
    # threaded processes, which is the cheapest way to use spare cores here.
    rf = os.path.join(WORKDIR, os.environ.get("POE_RESULT", "result.json"))
    for b in (tiers or TIERS):
        t1 = time.time()
        r = solve(A, J, float(b), need)
        if not r:
            print(f"[<= {b:g}c] no feasible combo  ({time.time()-t1:.0f}s)", flush=True)
            continue
        s = summarize(*r)
        out[tkey(b)] = {"budget": b, "margin": MARGIN if margin is None else margin, **s}
        # Write after EVERY tier, not once at the end. Cost per tier grows steeply
        # with the budget (affordable A entries went 216 -> 5k -> 46k -> 131k on
        # the reference task), so the expensive tiers come last and a kill used to
        # throw away every cheap tier that had already succeeded.
        json.dump(out, open(rf, "w"), indent=1)
        print(f"\n[<= {b:g}c] SCORE={s['score']:.0f}  life={s['life']} es={s['es']}  "
              f"spend={s['price']:.2f}c  F{s['res']['fire']} C{s['res']['cold']} "
              f"L{s['res']['light']} STR{s['res']['str']} DEX{s['res']['dex']}", flush=True)
        print(f"   ({time.time()-t1:.0f}s)", flush=True)
        if not quiet:
            for i in s["items"]:
                cr = f" 工藝:{i['craft']}" if i.get("craft") else ""
                print(f"   {i['slot']:6s} {i['raw']:>13s} L{i['life']:>4} ES{i['es']:>4} "
                      f"F{i['fire']:>3} C{i['cold']:>3} L{i['light']:>3} "
                      f"S{i['str']:>3} D{i['dex']:>3}  {i['name'][:30]:30s} "
                      f"@{i['seller']} [{i['pool']}]{cr}", flush=True)
    json.dump(out, open(rf, "w"), indent=1)
    print(f"\ntotal solve time {time.time()-t0:.1f}s", flush=True)
    return out


# ------------------------- selftest -------------------------
def selftest_parse():
    """Attribute/ES parsing is where a silent off-by-one hides. Pin it down."""
    cases = [
        ({"explicitMods": [{"description": "+42 to Strength and Dexterity"}]},
         {"str": 42, "dex": 42}),
        ({"explicitMods": [{"description": "+35 to Dexterity and Intelligence"}]},
         {"str": 0, "dex": 35}),
        ({"explicitMods": [{"description": "+21 to all Attributes"}]},
         {"str": 21, "dex": 21}),
        ({"explicitMods": [{"description": "+49 to Dexterity"},
                           {"description": "+52 to Strength"}]},
         {"str": 52, "dex": 49}),
        ({"implicitMods": [{"description": "Minions have +11% to all Elemental Resistances"}]},
         {"fire": 0, "cold": 0, "light": 0}),
        ({"implicitMods": [{"description": "+15 to maximum Energy Shield"}],
          "explicitMods": [{"description": "+46 to maximum Energy Shield"}]},
         {"es_mod": 61}),
        ({"explicitMods": [{"description": "+16% to Fire and Cold Resistances"}]},
         {"fire": 16, "cold": 16, "light": 0}),
        # PENALTIES -- these exist on real listings and must not read as zero
        ({"explicitMods": [{"description": "-60% to Lightning Resistance"}]},
         {"light": -60}),
        ({"explicitMods": [{"description": "+42% to Fire Resistance"},
                           {"description": "-58% to Lightning Resistance"}]},
         {"fire": 42, "light": -58}),
        ({"explicitMods": [{"description": "-20 to maximum Life"}]}, {"life": -20}),
        # "Adds 10 to 18 Fire Damage to Attacks" must not be read as resistance
        ({"explicitMods": [{"description": "Adds 10 to 18 Fire Damage to Attacks"}]},
         {"fire": 0, "life": 0}),
    ]
    bad = 0
    for item, want in cases:
        got, _, _, _, _ = _scan_mods(item)
        for k, v in want.items():
            if got[k] != v:
                print(f"  PARSE FAIL {item} -> {k}={got[k]} want {v}")
                bad += 1
    # es_of must not double count on armour, and must read mods on jewellery
    armour = {"extended": {"es": 284}, "explicitMods": [{"description": "+49 to maximum Energy Shield"}]}
    d, _, _, _, _ = _scan_mods(armour)
    if es_of(armour, "helm", d) != 284:
        print("  ES FAIL armour should use extended.es only"); bad += 1
    jewel = {"extended": {}, "explicitMods": [{"description": "+46 to maximum Energy Shield"}]}
    d, _, _, _, _ = _scan_mods(jewel)
    if es_of(jewel, "ring", d) != 46:
        print("  ES FAIL jewellery should use mod text"); bad += 1

    # --- craft eligibility: corrupted / MIRRORED / suffix cap ---------------
    # craft_mod={} means "parsed by a build that records crafts, and this item has
    # none" -- a row WITHOUT the key is a stale cache entry and must be refused
    # (covered separately above).
    base = {"native_suffix": 1, "suffix_cap": 3, "slot": "ring", "craft_mod": {}}
    checks = [
        (dict(base), True, "plain rare with a free suffix"),
        (dict(base, corrupt=True), False, "corrupted"),
        (dict(base, mirrored=True), False, "MIRRORED -- frozen forever"),
        (dict(base, native_suffix=3), False, "suffixes full"),
        # the reference Reflecting-Mist ring: "-2 Suffix Modifiers allowed" so the
        # cap is 1, and its single slot is already spent
        (dict(base, native_suffix=1, suffix_cap=1), False, "mist ring, cap 1, 1 used"),
        (dict(base, native_suffix=0, suffix_cap=1), True, "mist ring, cap 1, 0 used"),
    ]
    for c, want, why in checks:
        if has_free_suffix(c) != want:
            print(f"  CRAFT FAIL ({why}): got {has_free_suffix(c)}, want {want}")
            bad += 1
    # --- frontier() must survive NEGATIVE scores --------------------------
    # A ring with "-131 to maximum Life" scores 220*-131 = -28820. The old
    # running-maximum sentinel was -1, so such a group failed `score > best` on
    # the first entry and its whole clamped state vanished -- solve() then
    # returned None on a problem brute force answered at 212532 (selftest
    # seed 10, 2026-08-03).
    #
    # This lives here, as a DETERMINISTIC case, on purpose. The randomised
    # brute-force cross-check does catch it -- but only when the sample happens
    # to draw a negative-score listing, which depends on the cached pool of the
    # day: the very same 12-seed run passed before `reparse` changed the
    # candidate set and failed after. RNG is not a regression guard.
    neg = [(10.0, 220 * -131, (5, 0, 0, 0, 0), ())]
    if len(frontier(neg)) != 1:
        print("  FRONTIER FAIL: a lone negative-score aggregate was dropped")
        bad += 1
    # boundary: the old sentinel kept 0 and dropped -1
    for sc in (1, 0, -1, -2):
        if len(frontier([(1.0, sc, (0, 0, 0, 0, 0), ())])) != 1:
            print(f"  FRONTIER FAIL: lone aggregate with score {sc} was dropped")
            bad += 1
    # and it must still prune a dominated entry, negative or not
    dom = [(1.0, -500, (0, 0, 0, 0, 0), ()), (2.0, -900, (0, 0, 0, 0, 0), ())]
    if len(frontier(dom)) != 1:
        print("  FRONTIER FAIL: dearer-and-worse entry should be pruned")
        bad += 1

    # --- craft SWAP accounting -------------------------------------------
    # Reference item: Apocalypse Dome Lich's Circlet, 2026-08-03. Its third
    # suffix is a BENCH CRAFT ("+13 to Strength and Intelligence", `of Craft`
    # S0). Putting +35% fire on it means removing that craft, so 13 strength --
    # and the 6 life that Strength//2 contributed -- must come off too.
    helm_raw = {"item": {"id": "h1", "name": "Apocalypse Dome",
                         "baseType": "Lich's Circlet", "extended": {"es": 442},
                         "explicitMods": [
                             {"description": "+119 to maximum Life",
                              "mods": [{"name": "Athlete's", "tier": "P2"}]},
                             {"description": "+44% to Lightning Resistance",
                              "mods": [{"name": "of the Lightning", "tier": "S2"}]},
                             {"description": "+328 to Accuracy Rating",
                              "mods": [{"name": "of the Marksman", "tier": "S3"}]},
                             {"description": "+13 to Strength and Intelligence",
                              "domain": "crafted", "flags": {"crafted": True},
                              "mods": [{"name": "of Craft", "tier": "S0"}]}]},
                "id": "hash1",
                "listing": {"price": {"amount": 3, "currency": "divine"}}}
    row = parse_item(helm_raw, "q", "helm")
    if row["str"] != 13 or row["life"] != 119 + 6:
        print(f"  CRAFTSWAP FAIL base: str={row['str']} life={row['life']}")
        bad += 1
    variants = [v for v in expand_crafts([row]) if v.get("craft")]
    if not variants:
        print("  CRAFTSWAP FAIL: item with a reclaimable crafted suffix produced "
              "no craft variants"); bad += 1
    for v in variants:
        if v["str"] != 0 or v["life"] != 119 or v["flat"] != 119:
            print(f"  CRAFTSWAP FAIL {v['craft']}: str={v['str']} life={v['life']}"
                  " -- the replaced craft's strength was not removed")
            bad += 1
            break
    # an ES-touching craft on ARMOUR cannot be un-baked from extended.es
    es_craft = {"item": {"id": "h2", "name": "", "baseType": "Lich's Circlet",
                         "extended": {"es": 400},
                         "explicitMods": [
                             {"description": "+53 to maximum Energy Shield",
                              "domain": "crafted", "flags": {"crafted": True},
                              "mods": [{"name": "of Craft", "tier": "S0"}]}]},
                "id": "hash2",
                "listing": {"price": {"amount": 1, "currency": "chaos"}}}
    r2 = parse_item(es_craft, "q", "helm")
    if not r2["craft_es"] or has_free_suffix(r2):
        print("  CRAFTSWAP FAIL: armour with an ES bench craft must not be "
              "offered for craft swapping"); bad += 1
    # rows cached before craft_mod existed must not be craft-expanded on trust
    if has_free_suffix({"native_suffix": 0, "suffix_cap": 3, "slot": "helm"}):
        print("  CRAFTSWAP FAIL: a row with no craft_mod must not be craftable")
        bad += 1

    if _suffix_cap(["-2 Suffix Modifiers allowed", "+1 Prefix Modifier allowed"]) != 1:
        print("  SUFFIX-CAP FAIL: -2 Suffix Modifiers allowed should give cap 1")
        bad += 1
    if _suffix_cap(["+1 Suffix Modifier allowed"]) != 4:
        print("  SUFFIX-CAP FAIL: +1 should give cap 4"); bad += 1
    if _suffix_cap([]) != MAX_SUFFIX_DEFAULT:
        print("  SUFFIX-CAP FAIL: plain rare should be 3"); bad += 1

    # --- banned mods drop the listing entirely -----------------------------
    banned_item = {"item": {"id": "x", "name": "", "baseType": "Ring",
                            "extended": {},
                            "explicitMods": [{"description": "+266 to maximum Life"},
                                             {"description": "-33% to Global Critical Strike Multiplier"}]},
                   "id": "h", "listing": {"price": {"amount": 1, "currency": "chaos"}}}
    # the ban list is user-supplied and empty by default, so drive the test with
    # an explicit one rather than depending on whatever the user last chose
    _saved = BANNED_MODS[:]
    BANNED_MODS[:] = [r"-\d+% to Global Critical Strike Multiplier"]
    try:
        if parse_item(banned_item, "q", "ring") is not None:
            print("  BANNED FAIL: listing with a banned mod should be dropped")
            bad += 1
        BANNED_MODS[:] = []
        if parse_item(banned_item, "q", "ring") is None:
            print("  BANNED FAIL: empty ban list must keep the listing"); bad += 1
    finally:
        BANNED_MODS[:] = _saved
    # classifier: penalties we already score must NOT be offered as bans
    for text, want in (("-60% to Lightning Resistance", "modelled"),
                       ("-2 Suffix Modifiers allowed", "structural"),
                       ("-33% to Global Critical Strike Multiplier", "unmodelled")):
        if _negative_class(text) != want:
            print(f"  CLASS FAIL {text!r}: {_negative_class(text)} != {want}")
            bad += 1

    print(f"parse selftest: {'OK' if not bad else str(bad) + ' FAILURES'}")
    return bad


def _brute(sub, budget, need):
    bf = None
    for items in itertools.product(sub["helm"], sub["glove"], sub["ring"], sub["belt"]):
        if round(sum(i["price"] for i in items), 3) > budget + 1e-9:
            continue
        if any(sum(i[key] for i in items) < nd for key, nd in
               zip(("fire", "cold", "light", "str", "dex"), need)):
            continue
        sc = score_of(items)
        if bf is None or sc > bf:
            bf = sc
    return bf


def cmd_selftest(k=10, seeds=12):
    """Cross-check solve() against a literal 4-nested-loop brute force on random
    subsets. Run after ANY optimizer edit -- an off-by-one in the clamp or a
    mis-ordered dedup produces plausible-but-wrong answers, not crashes.

    !! A subset of k listings almost never satisfies the REAL requirement, so a
    test that only used it reported "all match" on six None==None rows and proved
    nothing. Scaled-down requirement vectors are what actually exercise the
    clamp/frontier/join; the full vector is kept as the last (usually infeasible)
    row so the infeasible path is covered too.

    !! SAMPLE SIZE IS THE WHOLE TEST. The 2026-08-02 version used ONE seed and
    five scales and reached 6 feasible cases -- it passed while the solver carried
    two real defects (a clamp that silently dropped its own best aggregate, and an
    axis shortcut that returned combos MISSING the requirement). Both need a
    negative-mod listing to be drawn into the subset, which one seed rarely does.
    Twelve seeds x six scales reaches ~200 feasible cases and catches both. Do not
    trim this back for speed; it runs in well under a minute.
    """
    import random
    bad = selftest_parse()
    full = needs()
    pools = load()
    if any(len(v) < 2 for v in pools.values()):
        sys.exit("not enough candidates cached -- run `pools` first")
    p = {kk: pareto(expand_crafts(v)) for kk, v in pools.items()}
    fails = tested = viol = 0
    for seed in range(1, seeds + 1):
        random.seed(seed)
        for scale in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0):
            need = tuple(int(round(n * scale)) for n in full)
            sub = {kk: random.sample(v, min(k, len(v))) for kk, v in p.items()}
            A, J = build_halves(sub, need)
            for budget in (60, 200, 600, 1200, BUDGET):
                bf = _brute(sub, budget, need)
                res = solve(A, J, float(budget), need)
                got = None
                if res:
                    s = summarize(*res)
                    got = round(s["score"] * 100)
                    if s["price"] > budget + 1e-9:
                        print(f"  OVER BUDGET {s['price']}>{budget}"); viol += 1
                    if len({i["id"] for i in s["items"]}) != 4:
                        print("  DUPLICATE LISTING"); viol += 1
                    for key, nd in zip(("fire", "cold", "light", "str", "dex"), need):
                        if s["res"][key] < nd:
                            print(f"  *** CONSTRAINT VIOLATED seed{seed} x{scale} "
                                  f"{budget:.0f}c: {key} {s['res'][key]}<{nd}")
                            viol += 1
                if bf is not None:
                    tested += 1
                if got != bf:
                    fails += 1
                    print(f"  *** MISMATCH seed{seed} x{scale} budget {budget:.0f}c: "
                          f"bf={bf} solve={got}")
    print(f"\n{tested} feasible cases exercised over {seeds} seeds"
          f"  (mismatches {fails}, constraint violations {viol})")
    if tested < 50:
        print("*** TOO FEW feasible cases -- raise k or seeds; this proves little ***")
        fails += 1
    print("RESULT:", "all match" if not (fails or bad or viol)
          else f"{fails + bad + viol} PROBLEMS")
    return 1 if (fails or bad or viol) else 0


# ------------------------- verification & buy links -------------------------
_VERIFY_JS = r"""
async page => await page.evaluate(async () => {
  const BODY = __BODY__, WANT = __WANT__;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const sr = await fetch('/api/trade/search/__LEAGUE_ENC__',
    {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(BODY)});
  if (!sr.ok) return JSON.stringify({error:'search '+sr.status});
  const s = await sr.json();
  await sleep(1500);
  let found = null;
  const hashes = (s.result||[]).slice(0,10);
  if (hashes.length) {
    const fr = await fetch('/api/trade/fetch/' + hashes.join(',') + '?query=' + s.id);
    if (fr.ok) {
      const j = await fr.json();
      for (const it of (j.result||[])) {
        if (it && it.item && it.item.id === WANT) {
          const p = (it.listing||{}).price || {};
          found = {price: p.amount + ' ' + p.currency, gone: !!it.gone};
        }
      }
    }
  }
  return JSON.stringify({qid:s.id, total:s.total, found});
})
"""


def seller_query(it):
    """Seller + slot + a floor on whichever stat identifies the piece. The account
    name MUST keep its #1234 discriminator or the search returns 0 SILENTLY."""
    stats = []
    if it["slot"] in ARMOUR_SLOTS:
        pass                      # ES is an armour_filter, not a stat
    elif it["es_mod"]:
        stats.append(SF(TOT_ES, it["es_mod"]))
    if it["life"]:
        stats.append(SF(TOT_LIFE, it["life"]))
    filters = {"type_filters": {"filters": {"category": {"option": CAT[it["slot"]]},
                                            "rarity": {"option": RARITY}}},
               "trade_filters": {"filters": {"account": {"input": it["seller"]}}}}
    if it["slot"] in ARMOUR_SLOTS and it["es"]:
        filters["armour_filters"] = {"filters": {"es": {"min": it["es"]}}}
    return {"query": {"status": {"option": "securable"},
                      "stats": [{"type": "and", "filters": stats}] if stats else [],
                      "filters": filters},
            "sort": {"price": "asc"}}


_HASH_FETCH_JS = r"""
async page => await page.evaluate(async () => {
  const QID = __QID__, HASHES = __HASHES__;
  const r = await fetch('/api/trade/fetch/' + HASHES.join(',') + '?query=' + QID);
  if (!r.ok) return JSON.stringify({error: 'fetch ' + r.status});
  return JSON.stringify(await r.json());
})
"""


def _fetch_hashes(qid, hashes):
    """An empty hash list MUST short-circuit: /fetch/?query=... returns 404, and
    that is the common case (item sold -> seller search returns nothing)."""
    hashes = [h for h in (hashes or []) if h]
    if not hashes:
        return []
    if transport() == "http":
        j = req(FETCH_URL.format(ids=",".join(hashes), qid=qid))
        # pacing handled by _rl_pace() in req(); a fixed sleep here just adds to it
    else:
        js = (_HASH_FETCH_JS.replace("__QID__", json.dumps(qid))
                            .replace("__HASHES__", json.dumps(hashes)))
        j = _playwright(js, "hashfetch")
    return [] if j.get("error") else (j.get("result") or [])


def live_by_hash(items):
    """Direct liveness via hash fetch, batched. A dead hash inside a valid batch
    comes back null without erroring, so "absent" is a reliable sold signal."""
    by_qid = {}
    for it in items:
        if it.get("hash") and it.get("qid"):
            by_qid.setdefault(it["qid"], []).append(it)
    found, resolved = {}, set()
    for qid, group in by_qid.items():
        for i in range(0, len(group), FETCH_CAP):
            batch = group[i:i + FETCH_CAP]
            try:
                results = _fetch_hashes(qid, [g["hash"] for g in batch])
            except Exception as e:
                print(f"  hash fetch failed for {qid} ({e}); falling back", flush=True)
                continue
            got = {x["item"]["id"]: x for x in results
                   if x and x.get("item") and not x.get("gone")}
            for g in batch:
                resolved.add(g["id"])
                if g["id"] in got:
                    p = (got[g["id"]].get("listing") or {}).get("price") or {}
                    found[g["id"]] = {"price": f"{p.get('amount')} {p.get('currency')}",
                                      "gone": False}
    return found, resolved


def verify_one(it, live=None, resolved=False):
    body = seller_query(it)
    need_fallback = live is None and not resolved
    mode = transport()
    if mode == "http":
        s = req(SEARCH_URL.format(league=LEAGUE), json.dumps(body).encode("utf-8"))
        # pacing handled by _rl_pace() in req(); a fixed sleep here just adds to it
        qid, total = s["id"], s.get("total")
        if need_fallback:
            for x in _fetch_hashes(qid, (s.get("result") or [])[:FETCH_CAP]) or []:
                if x and x.get("item", {}).get("id") == it["id"]:
                    p = (x.get("listing") or {}).get("price") or {}
                    live = {"price": f"{p.get('amount')} {p.get('currency')}",
                            "gone": bool(x.get("gone"))}
        d = {"qid": qid, "total": total}
    else:
        js = (_VERIFY_JS.replace("__BODY__", json.dumps(body))
                        .replace("__WANT__", json.dumps(it["id"]))
                        .replace("__LEAGUE_ENC__", LEAGUE.replace(" ", "%20")))
        d = _playwright(js, "verify")
        if need_fallback:
            live = d.get("found")
    return {**it, "url": RESULT_URL.format(league=LEAGUE.replace(" ", "%20"),
                                           qid=d.get("qid", "")),
            "seller_total": d.get("total"), "live": bool(live),
            "live_price": (live or {}).get("price"),
            "live_via": "hash" if resolved else "seller-search"}


def cmd_verify(tier=None):
    res = json.load(open(os.path.join(WORKDIR, "result.json")))
    tier = tkey(tier) if tier is not None else max(res, key=lambda k: float(k))
    items = res[tier]["items"]
    hashed, resolved = live_by_hash(items)
    out = [verify_one(it, hashed.get(it["id"]), it["id"] in resolved) for it in items]
    for i in out:
        print(f"{i['slot']:6s} {i['name'][:30]:30s} @{i['seller']:20s} "
              f"total={i['seller_total']} live={i['live']} [{i['live_via']}] "
              f"{i['live_price'] or ''}")
    payload = {"verified_at": time.strftime("%Y-%m-%d %H:%M"), "tier": tier,
               "score": res[tier]["score"], "life": res[tier]["life"],
               "es": res[tier]["es"], "price": res[tier]["price"],
               "res": res[tier]["res"], "items": out}
    json.dump(payload, open(os.path.join(WORKDIR, f"verified_{tier}.json"), "w"), indent=1)
    print(f"\nall_live={all(i['live'] for i in out)} -> verified_{tier}.json")
    return payload


def cmd_converge(tiers=None, rounds=6):
    targets = [tkey(t) for t in (tiers or [TIERS[-1]])]
    for rnd in range(1, rounds + 1):
        print(f"\n===== round {rnd} =====", flush=True)
        cmd_solve(tiers=[float(t) for t in targets], quiet=True)
        dead, ok = set(), True
        for t in targets:
            v = cmd_verify(t)
            gone = [i for i in v["items"] if not i["live"]]
            print(f"  tier {t}c: {len(v['items']) - len(gone)}/{len(v['items'])} live")
            for i in gone:
                print(f"     SOLD {i['slot']} {i['name'][:30]} {i['raw']} @{i['seller']}")
                dead.add(i["id"])
            ok &= not gone
        if ok:
            print("\nCONVERGED: every item in every target tier is live.")
            return True
        print(f"  excluded {len(dead)} newly sold; total {len(add_sold(dead))}")
    print("\nNOT CONVERGED -- market churning faster than we solve.")
    return False


# ------------------------- report -------------------------
def cmd_report(tiers=None, out_dir=None):
    tiers = [tkey(t) for t in (tiers or [TIERS[-1]])]
    solver_note = ("精確解（每部位候選全數納入，與 4 層暴力解對拍相符）" if not FAST else
                   f"瘦身模式 `POE_FAST={FAST}`（每部位保留約 {FAST} 個實體候選再展開工藝）。"
                   "⚠ 這是有損模式，**只會低估、不會給出買不到或不達標的組合**；"
                   "引用為「理論上限」前請看下方的收斂階梯")
    ladder = os.environ.get("POE_LADDER", "")
    vs = []
    for t in tiers:
        p = os.path.join(WORKDIR, f"verified_{t}.json")
        if not os.path.exists(p):
            sys.exit(f"missing {p} -- run `verify {t}` first")
        vs.append(json.load(open(p)))
    pool_qid = {}
    for fn in glob.glob(os.path.join(WORKDIR, "parsed_*.json")):
        d = json.load(open(fn))
        pool_qid[d["name"]] = d["qid"]
    shared = set.intersection(*[{i["id"] for i in v["items"]} for v in vs]) if len(vs) > 1 else set()

    L = [f"# POE1 配裝查詢結果 — 生命＋ES 加權（{LEAGUE}）", "",
         f"- **產生時間**：{time.strftime('%Y-%m-%d %H:%M')}",
         f"- **部位**：{'／'.join(ZH[s] for s in SLOT_ORDER)} 共 {len(SLOT_ORDER)} 件",
         f"- **預算**：{BUDGET:.0f} chaos（= 10 divine，1 div = {DIV:.2f}c）",
         f"- **抗性需求**：火 {NEED_RES[0]}% / 冰 {NEED_RES[1]}% / 雷 {NEED_RES[2]}%"
         f"（緩衝 +{MARGIN}）｜**屬性需求**：力量 {NEED_STR}、敏捷 {NEED_DEX}",
         f"- **目標函數**：`{W_LIFE} × 生命 + {W_ES} × ES`，在滿足上述所有硬約束下最大化",
         "- **生命口徑**：`+# to maximum Life` + 力量÷2（力量含 `Strength and X`／`all Attributes`）",
         "- **ES 口徑**：頭盔／手套取 `extended.es`（＝**20% 品質校正值**，交易站的 ES 篩選器"
         "用的也是這個數字）；戒指／腰帶取 `+# to maximum Energy Shield` 詞綴（全域平擊）",
         f"- **限制**：{RARITY} 裝；不設需求等級上限；Instant Buyout（`securable`）",
         f"- **求解模式**：{solver_note}"
         + ("；**含工藝補抗**（買未腐化、後綴有空位的便宜貨，自己上抗性工藝）" if CRAFT else ""),
         *([f"- **收斂階梯**：{ladder}"] if ladder else []), ""]

    for v in vs:
        # Describe what THIS combo actually does. A canned sentence ("the ring
        # carries dex, the belt carries strength") goes stale the moment the
        # solver picks a different allocation -- and it did: on the reference run
        # the GLOVES carried all 41 dex and the ring carried none.
        def _carriers(key):
            return "／".join(ZH[i["slot"]] for i in sorted(
                v["items"], key=lambda x: -x[key]) if i[key] > 0) or "無"
        crafted = [i for i in v["items"] if i.get("craft")]
        es_rank = sorted(v["items"], key=lambda i: -i["es"])[:2]
        es_txt = "／".join(f"{ZH[i['slot']]} {i['es']}" for i in es_rank)
        craft_txt = ("；" + str(len(crafted)) + " 件靠工藝後綴補抗（"
                     + "、".join(f"{ZH[i['slot']]} {i['craft']}%" for i in crafted)
                     + "）。") if crafted else "；未動用工藝。"
        L += [f"## 方案：{v['price']:.1f}c，加權分 {v['score']:.0f}", "",
              f"- **描述**：ES 主要來自 {es_txt}；敏捷由 {_carriers('dex')} 提供，"
              f"力量由 {_carriers('str')} 提供{craft_txt}",
              f"- **總價格**：**{v['price']:.1f} chaos**（約 {v['price']/DIV:.2f} divine，"
              f"佔預算 {v['price']/BUDGET*100:.0f}%）",
              f"- **加權分**：**{v['score']:.0f}** ＝ {W_LIFE}×生命 {v['life']} + {W_ES}×ES {v['es']}",
              "- **需求檢核**：" + "｜".join(
                  [f"{n} **{v['res'][k]}** / 需求 {nd}（+{v['res'][k]-nd}）"
                   for k, n, nd in zip(("fire", "cold", "light"), ("火抗", "冰抗", "雷抗"), NEED_RES)]
                  + [f"力量 **{v['res']['str']}** / 需求 {NEED_STR}（+{v['res']['str']-NEED_STR}）",
                     f"敏捷 **{v['res']['dex']}** / 需求 {NEED_DEX}（+{v['res']['dex']-NEED_DEX}）"]),
              f"- **驗證在架**：{v['verified_at']} 逐件 hash fetch 確認"
              f"（{'全部 live' if all(i['live'] for i in v['items']) else '⚠ 部分已售出'}）", "",
              "| 部位 | 名稱 | 關鍵屬性 | 價格 | 購買連結 | 備註 |",
              "|---|---|---|---|---|---|"]
        for it in v["items"]:
            es_txt = f"ES **{it['es']}**"
            needs_q = (it["slot"] in ARMOUR_SLOTS and it.get("es_now")
                       and it["es_now"] < it["es"])
            if needs_q:
                es_txt += f"（現況 {it['es_now']}，補到 20% 品質後 {it['es']}）"
            attr = (f"{es_txt}<br>Life **{it['life']}**（flat {it['flat']}"
                    + (f" + 力量 {it['str']}/2" if it["str"] else "") + "）"
                    + f"<br>火 {it['fire']} / 冰 {it['cold']} / 雷 {it['light']}"
                    + (f"<br>力量 {it['str']}" if it["str"] else "")
                    + (f" 敏捷 {it['dex']}" if it["dex"] else ""))
            note = []
            if it.get("craft"):
                note.append(f"**買回來上工藝：{it['craft']}%**（已計入左欄抗性）")
            # only when it actually needs it -- blanket-tagging every armour piece
            # made the note noise on items already sitting at 20% quality
            if needs_q:
                note.append("**補品質到 20%**")
            if it["id"] in shared:
                note.append("**多套共用同一件**")
            if it.get("corrupt"):
                note.append("已腐化（不能上工藝）")
            if it.get("mirrored"):
                note.append("**Mirrored（複製品）——永久定型，任何工藝都不能上**")
            if it.get("negatives"):
                note.append("⚠ 負面詞綴：" + "、".join(f"`{t}`" for t in it["negatives"]))
            # `reduced` / `less` lines are NOT listed as negatives: plenty of them
            # are upside ("reduced Enemy Stun Threshold", "reduced Attribute
            # Requirements", "reduced Freeze Duration on you"). But NEGATIVE_RE
            # only sees a leading minus sign, so before this they were invisible
            # in the deliverable -- the 2026-08-03 winner shipped a mirrored ring
            # carrying "46% reduced Elemental Damage with Attack Skills" with no
            # mention anywhere. Surface them verbatim and let the buyer judge.
            red = [t for t in (it.get("mods") or []) if REDUCED_RE.search(t)]
            if red:
                note.append("含 reduced 詞綴（請自行判斷利弊）："
                            + "、".join(f"`{t}`" for t in red))
            if (it.get("seller_total") or 1) > 1:
                note.append(f"該賣家有 {it['seller_total']} 件符合，認價格 {it['raw']}")
            if not it["live"]:
                note.append("**⚠ 已售出，請改用替代連結**")
            alt = pool_qid.get(it.get("pool"))
            if alt:
                note.append(f"[同規格替代]({RESULT_URL.format(league=LEAGUE, qid=alt)})")
            L.append(f"| {ZH[it['slot']]} | {it['name']} | {attr} | {it['raw']}"
                     f"（{it['price']:.1f}c） | [打開]({it['url']}) | "
                     f"{'；'.join(note) or '—'} |")
        L.append("")

    dead = [i for v in vs for i in v["items"] if not i["live"]]
    live_note = ("- **⚠ 本輪未執行 `converge`，且上表有 "
                 + str(len(dead)) + " 件在驗證當下已售出**（"
                 + "、".join(f"{ZH[i['slot']]} {i['name']}" for i in dead)
                 + "）。這份是**規格驗收用**的快照，不是可直接照買的清單；"
                 "要實際採買請重跑一輪並 `converge` 到全部在架。"
                 ) if dead else (
                 "- **交付前已逐件確認全部在架**，但這個價位分鐘級售出，拖久仍可能失效。")
    L += ["## 通用注意事項", "",
          "- **頭盔／手套的 ES 數字是 20% 品質校正值**（交易站 ES 篩選器的口徑）。"
          "若某件的「現況」低於表列值，備註會標「補品質到 20%」——沒標的就是已經是 20% 品質。",
          live_note,
          "- 連結失效就用備註的「同規格替代」挑同級品，抗性差額從其他部位補。",
          "- **購買連結是「賣家＋部位＋規格下限」的過濾搜尋**（帳號名含 `#1234`，缺了會靜靜回 0 筆）。",
          "- **智慧（Int）沒有計入加權分**：POE1 的 int 給的是 %增加 ES 而非固定值，"
          "無法用「每點 ES ×2.41」的口徑折算。挑到的 ES 底本身需求大量 int，實際收益比表上更高。",
          "- **力量換血已計入**（力量÷2）；實際面板還會再吃天賦的 %increased Life／%increased ES。", ""]

    root = out_dir or os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                   "..", "..", "..", ".."))
    fn = os.path.join(root, f"search_results_{time.strftime('%Y%m%d%H%M')}.md")
    open(fn, "w", encoding="utf-8").write("\n".join(L))
    print("wrote", fn)
    return fn


# ------------------------- main -------------------------
def main():
    cmds = {"probe", "pools", "deep", "reparse", "negatives", "solve", "verify",
            "converge", "report", "selftest"}
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    cmd = argv[0] if argv else "solve"
    if cmd not in cmds:
        sys.exit(__doc__.split("Usage:")[1].split("Requires")[0])
    os.makedirs(WORKDIR, exist_ok=True)
    BANNED_MODS[:] = _load_banned()
    if BANNED_MODS:
        print(f"banned mods ({len(BANNED_MODS)}): {BANNED_MODS}", flush=True)
    rest = argv[1:]
    if cmd == "negatives":
        cmd_negatives()
    elif cmd == "probe":
        cmd_probe()
    elif cmd == "pools":
        cmd_pools(force="--force" in sys.argv)
    elif cmd == "deep":
        cmd_deep(int(rest[0]) if rest else 100)
    elif cmd == "reparse":
        cmd_reparse()
    elif cmd == "solve":
        cmd_solve(tiers=[float(x) for x in rest] or None)
    elif cmd == "verify":
        cmd_verify(rest[0] if rest else None)
    elif cmd == "converge":
        sys.exit(0 if cmd_converge(rest or None) else 1)
    elif cmd == "report":
        cmd_report(rest or None)
    elif cmd == "selftest":
        sys.exit(cmd_selftest())


if __name__ == "__main__":
    main()
