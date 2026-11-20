# -*- coding: utf-8 -*-
"""Multi-slot gear optimizer for POE1 /trade -- LIFE objective, FOUR resistance
axes including CHAOS, five slots each with its own hard requirements.

!! REALM: POE1 ONLY. Third POE1 sibling, after gear_combo_optimizer_poe1.py
!! (pure life, 6 slots, 3 axes) and gear_combo_es_poe1.py (life+ES, 4 slots,
!! 5 axes). Every endpoint, field name, stat id, currency and mod regex is a
!! POE1 profile re-derived from ../poe1/QUERY.md + ../poe1/references/stats.tsv.
!! A wrong-game stat id can be SILENTLY VALID and quietly return wrong items.

WHY A THIRD SCRIPT:
  * CHAOS RESISTANCE is a constraint axis. Neither sibling parses it at all --
    gear_combo_es_poe1.py deliberately discards the chaos half of the
    "+#% to Fire and Chaos Resistances" hybrids ("chaos res is out of scope").
  * FIVE slots, two of them the SAME CATEGORY (two rings) -- the pair must be
    two DIFFERENT listings, which no sibling has to enforce.
  * Each slot carries its own hard search-time requirements (shaper influence,
    movement speed, cooldown recovery, a temple hybrid, "no Life modifiers at
    all", "a prefix free for a bench craft"), so there is no single q() shape.
  * Objective is life alone. ES/evasion/armour are reported, never scored.

Built 2026-09-05 on Allflame for a Deadeye bow build:
  "buy boots + gloves + body + 2 rings within 10 divine; cover fire 39 /
   cold 58 / lightning 39 / CHAOS 100; maximise total life."

VALIDATED END TO END 2026-09-05: the user actually bought the CP-tier answer
(1158c of a 4200c budget) and confirmed in game that every requirement was met.
So the whole chain held against reality, not just against the selftest -- the
chaos axis, the craft-swap subtraction on rings, the same-colour craft
exclusivity, the "no Life modifier on the body armour" gate, and the price
conversion. Treat a change that breaks any of those as a regression.

Pipeline (../common/tricks.md):
    probe -> pools -> deep -> solve -> verify -> converge -> report

Usage:
    python gear_combo_res4_poe1.py selftest   # brute-force check the solver FIRST
    python gear_combo_res4_poe1.py probe
    python gear_combo_res4_poe1.py pools
    python gear_combo_res4_poe1.py deep       # extend pools to 100 w/o re-searching
    python gear_combo_res4_poe1.py negatives  # ASK the user which downsides to ban
    python gear_combo_res4_poe1.py solve
    python gear_combo_res4_poe1.py verify
    python gear_combo_res4_poe1.py converge
    python gear_combo_res4_poe1.py report

Requires numpy. Everything else is stdlib.

MEASURED / DECIDED, do not relearn the hard way:
  * RINGS GET NO BENCH CRAFT. An item holds ONE crafted mod
    (../poe1/knowledge/crafting.md) and the user spends each ring's on a
    "-# to Total Mana Cost of Skills" PREFIX. So a ring's resistance must be
    native, and any crafted mod already on it is SUBTRACTED (user 2026-09-05:
    "你要用拿掉他之後的數值做計算"). Armour slots still get craft expansion.
  * SAME-COLOUR SINGLE-ELEMENT RESISTANCES ARE MUTUALLY EXCLUSIVE
    (../poe1/knowledge/crafting.md, user 2026-09-05). An item already carrying a
    native "+#% to Fire Resistance" can never take the bench's +35% fire. The
    older siblings do not check this and can therefore deliver combos that
    cannot be built. Here _scan_mods() records the mod GROUP of every native
    resistance line and expand_crafts() refuses a craft whose group is taken.
  * THERE IS NO PURE-CHAOS BENCH CRAFT. The bench offers single-element (35),
    dual-element (20/20), element+chaos (15/15) and -- jewellery only --
    all-elemental (12x3). Chaos arrives natively or via element+chaos.
  * THE BODY ARMOUR MUST CARRY NO LIFE MODIFIER AT ALL. Not a preference: the
    build allocates the Life Mastery "15% increased maximum Life if there are no
    Life Modifiers on Equipped Body Armour" (user 2026-09-05). One stray life
    mod costs 15% of the WHOLE character's life, which dwarfs anything the mod
    itself could give. Enforced twice: a `not` stat group at search time and
    BODY_LIFE_RE over the mod text at parse time (the authoritative gate).
  * pseudo_total_life = flat life + Strength//2, and integer division does NOT
    distribute over subtraction, so life is RECOMPUTED after a craft swap.
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
WORKDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "gear_pools_poe1_res4")

DIV = 419.9792               # 1 divine in chaos; poe2scout /api/pc/Leagues 2026-09-05
BUDGET = round(10 * DIV, 2)  # 10 divine
# PoB MissingFireResist / MissingColdResist / MissingLightningResist, and
# chaos = 40 - (-60). Read off the build 2026-09-05; all max resistances are 75.
NEED = (39, 58, 39, 100)     # (fire, cold, lightning, CHAOS)
MARGIN = 0                   # user wants exact-on-target
REQ_LVL_MAX = None
RARITY = "rare"
N_PER_POOL = 30

TIERS = (600, 1200, 2000, 3000, BUDGET)

# chaos-denominated, poe2scout /api/pc/Leagues/Allflame/SnapshotPairs 2026-09-05
# (poe2scout is retired; refresh with the poe-currency-price skill: cx.py price <names>).
# ALWAYS re-fetch: 1 div moved 174 -> 420 between 2026-08-02 and 2026-09-05.
# `mirror` is deliberately absent -- out of budget by definition, and an unknown
# currency makes parse_item() drop the listing rather than mis-price it.
RATES = {"chaos": 1.0, "divine": DIV, "exalted": 1.9202, "annul": 21.1157,
         "chrome": 6.2232, "gcp": 2.9302, "regret": 1.5660, "vaal": 0.7837,
         "scour": 0.9191, "blessed": 0.4047, "regal": 0.0589, "fusing": 0.1322,
         "alt": 0.1661, "chance": 0.1290, "alch": 0.0485, "jewellers": 0.0119,
         "transmute": 0.0046, "aug": 0.0439, "bauble": 0.5662,
         "whetstone": 0.0175}

# UA discipline (../common/tricks.md): the ONLY source is .poe_cookies.json,
# which stores the UA the cookie was captured under. A drifting UA gets
# POESESSID revoked. The literal below is a last-resort fallback.
_UA_FALLBACK = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

SLOT_ORDER = ["boots", "glove", "body", "ring1", "ring2"]
CAT = {"boots": "armour.boots", "glove": "armour.gloves", "body": "armour.chest",
       "ring1": "accessory.ring", "ring2": "accessory.ring"}
ZH = {"boots": "鞋子", "glove": "手套", "body": "身體", "ring1": "戒指1",
      "ring2": "戒指2"}
# Slots that may take a bench resistance craft. Rings are excluded by the USER'S
# DECISION (their one craft goes to -mana cost), not by a game rule.
CRAFT_SLOTS = {"boots", "glove", "body"}
RING_SLOTS = {"ring1", "ring2"}

FAST = int(os.environ.get("POE_FAST", "200"))
CRAFT = int(os.environ.get("POE_CRAFT", "1"))
# POE_TEMPLE=fire restricts the glove pool to gloves whose temple hybrid is
# ALREADY the fire flavour. Why this exists as a switch rather than a default:
# the temple modifier carries a single-element resistance, so horticrafting it
# to another colour MOVES THAT RESISTANCE TOO (../poe1/knowledge/horticrafting.md).
# The unconstrained optimum picked a cold-flavoured glove whose +46% cold was
# load-bearing -- recolouring it to fire would have dropped cold from 80 to 34
# against a requirement of 58. So "buy any colour and convert" is NOT free here,
# and the honest answer is two solves: the max-life one, and one that needs no
# conversion at all.
TEMPLE_ONLY = os.environ.get("POE_TEMPLE", "").strip().lower()
# Order-of-magnitude only; calibrated on the 5-axis sibling, axis count differs.
_ETA_GROUPS_PER_SEC = 3.23e9
NAX = 4
RES_AXES = ("fire", "cold", "light", "chaos")
# ======================================================================


def save_json(path, obj, **kw):
    """Atomic write -- an interrupted run must not destroy the previous file.

    Pool caches hold data that took tens of minutes to fetch under a rate limit;
    a truncated parsed_*.json means re-fetching all of it.
    """
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, **kw)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


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

# ---------------------- rate limiting (../common/tricks.md) --------------
# Self-paced: keep our own timestamps, seeded from the server's counters, and
# sleep only until a slot actually frees. Never sleep a whole window -- the
# 3-hour rule's period is 10800s and sleeping it looks exactly like a hang.
_RL = {}
MIN_INTERVAL = 0.6            # anti-rapid-click floor
BACKSTOP_FRACTION = 0.10


def _rl_key(url):
    return "fetch" if "/api/trade/fetch/" in url else "search"


def _rl_observe(key, hdrs):
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
    # Back-fill band by band, shortest window outwards. The windows are nested;
    # spreading the outer count over the whole outer period inflates the inner
    # one (measured cost of getting this wrong: a 574s pace where 65s was right).
    counts.sort(key=lambda cp: cp[1])
    prev_per = prev_cur = 0
    for cur, per in counts:
        want = cur - prev_cur
        mine = sum(1 for t in st["hits"] if prev_per <= now - t < per)
        gap, span = want - mine, per - prev_per
        if gap > 0 and span > 0:
            st["hits"].extend(now - (prev_per + span * (i + 0.5) / gap)
                              for i in range(gap))
        prev_per, prev_cur = per, max(prev_cur, cur)
    horizon = max((p for _, p in st["rules"]), default=0)
    st["hits"] = sorted(t for t in st["hits"] if now - t < horizon)


def _rl_pace(key):
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
            drop = len(recent) - room + 1
            window = max(window, recent[drop - 1] + per - now)
    # 0.2s covers clock skew against a WINDOW BOUNDARY; it must not inflate the
    # anti-rapid-click floor, which is an absolute spacing.
    if window > 0:
        window += 0.2
    floor = (hits[-1] + MIN_INTERVAL - now) if hits else 0.0
    delay = max(window, floor)
    if delay > 0:
        print(f"  pacing {delay:.2f}s (self-tracked, no stall)", flush=True)
        time.sleep(delay)
    _RL[key]["hits"].append(time.time())


def _throttle_wait(hdrs):
    """Backstop on top of _rl_pace(): react to what the SERVER says."""
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
        print(f"{name:28s} cached id={j.get('id')} total={j.get('total')}", flush=True)
        return j
    j = req(SEARCH_URL.format(league=LEAGUE), json.dumps(body).encode("utf-8"))
    save_json(f, j)
    print(f"{name:28s} id={j.get('id')} total={j.get('total')}", flush=True)
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
    return {"qid": qid, "total": s.get("total"), "rows": rows}


# ------------------ transport: in-page fetch (browser) ------------------
# Fallback for a dead POESESSID (../common/tricks.md). Parsing stays in Python
# so MOD_PATTERNS has exactly one definition.
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
      const m = it.item;
      out.push({id: it.id, item: {id: m.id, name: m.name, baseType: m.baseType,
        ilvl: m.ilvl, corrupted: m.corrupted, duplicated: m.duplicated,
        influences: m.influences,
        extended: {es: (m.extended||{}).es, ev: (m.extended||{}).ev, ar: (m.extended||{}).ar},
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
            req(SEARCH_URL.format(league=LEAGUE),
                json.dumps(slot_query("body", [])).encode("utf-8"))
        except Exception:
            _auth_ok = False
    return "http" if _auth_ok else "browser"


def run_pool(name, body, need=N_PER_POOL, force=False):
    os.makedirs(WORKDIR, exist_ok=True)
    out_f = os.path.join(WORKDIR, f"parsed_{name}.json")
    if os.path.exists(out_f) and not force:
        d = json.load(open(out_f))
        print(f"{name:28s} cached qid={d.get('qid')} rows={len(d.get('rows', []))}",
              flush=True)
        return d
    mode = transport()
    d = (http_pool if mode == "http" else browser_pool)(name, body, need)
    save_json(out_f, {"name": name, "body": body, **d})
    print(f"{name:28s} [{mode}] qid={d['qid']} total={d['total']} rows={len(d['rows'])}",
          flush=True)
    return d


# ------------------------- query builders -------------------------
# Freshly grepped from ../poe1/references/stats.tsv (2026-09-05). NEVER reuse a
# stat id from memory or from the POE2 tree -- 274 explicit hashes mean something
# DIFFERENT in the other game and the API will not complain.
TOT_LIFE = "pseudo.pseudo_total_life"                 # flat life + Strength/2
TOT_RES = "pseudo.pseudo_total_elemental_resistance"
TOT_FIRE = "pseudo.pseudo_total_fire_resistance"
TOT_COLD = "pseudo.pseudo_total_cold_resistance"
TOT_LIGHT = "pseudo.pseudo_total_lightning_resistance"
TOT_CHAOS = "pseudo.pseudo_total_chaos_resistance"
SHAPER = "pseudo.pseudo_has_shaper_influence"
MOVE_SPEED = "pseudo.pseudo_increased_movement_speed"
EMPTY_PREFIX = "pseudo.pseudo_number_of_empty_prefix_mods"
CRAFTED_PREFIX = "pseudo.pseudo_number_of_crafted_prefix_mods"
EMPTY_SUFFIX = "pseudo.pseudo_number_of_empty_suffix_mods"
CRAFTED_SUFFIX = "pseudo.pseudo_number_of_crafted_suffix_mods"

# "#% increased Cooldown Recovery Rate" appears TWICE in stats.tsv with identical
# text (explicit.stat_1004011302 and explicit.stat_239144). Which one the boots
# mod actually uses is not decidable from the table, so both go into a `count`
# group -- an OR that is correct whichever it is. `probe` measures each alone so
# the answer gets recorded rather than guessed.
CDR_IDS = ("explicit.stat_1004011302", "explicit.stat_239144")

# Temple ("神廟詞") glove hybrids: one modifier that grants damage AND a single
# elemental resistance, which is why horticrafting can recolour it and drag the
# damage type along (../poe1/knowledge/horticrafting.md).
TEMPLE_IDS = {"fire": "explicit.stat_165402179",     # # to # added Fire Damage against Burning Enemies
              "cold": "explicit.stat_2805714016",    # #% increased Damage with Hits against Chilled Enemies
              "light": "explicit.stat_276103140"}    # #% increased Crit Chance against Shocked Enemies
TEMPLE_RE = {"fire": re.compile(r"added Fire Damage against Burning Enemies"),
             "cold": re.compile(r"Damage with Hits against Chilled Enemies"),
             "light": re.compile(r"Critical Strike Chance against Shocked Enemies")}

# Body armour must carry NO Life modifier -- the build's Life Mastery grants
# "15% increased maximum Life if there are no Life Modifiers on Equipped Body
# Armour". These ids narrow the pool at search time; BODY_LIFE_RE below is the
# authoritative gate, because a `not` group over explicit ids does not see
# fractured/implicit copies of the same mod.
BODY_LIFE_BAN = ["explicit.stat_3299347043",   # +# to maximum Life
                 "explicit.stat_983749596",    # #% increased maximum Life
                 "explicit.stat_3325883026",   # Regenerate # Life per second
                 "explicit.stat_836936635",    # Regenerate #% of Life per second
                 "explicit.stat_3593843976",   # #% of Physical Attack Damage Leeched as Life
                 "explicit.stat_3899352861"]   # #% increased max Life, Mana and Global ES


def SF(sid, mn=None):
    f = {"id": sid, "disabled": False}
    if mn is not None:
        f["value"] = {"min": mn}
    return f


def slot_query(slot, stat_filters, rarity=RARITY):
    """POE1 query body for one slot, with that slot's HARD requirements baked in.

    status/sort live at the ROOT, not inside filters. Deliberately NO price cap:
    the literal-currency cap silently drops listings priced in exalted/chrome/
    alch (../poe1/knowledge/market.md).

    The evasion requirement is `armour_filters.ev >= 1`, which doubles as "this
    is an evasion or evasion-hybrid base" -- a pure armour or pure ES base has no
    evasion value at all. The build needs all four of helmet/body/gloves/boots to
    have evasion for the Evasion Mastery suppression bonus.
    """
    stats = [{"type": "and", "filters": list(stat_filters)}]
    filters = {"type_filters": {"filters": {"category": {"option": CAT[slot]}}}}
    if rarity:
        filters["type_filters"]["filters"]["rarity"] = {"option": rarity}
    misc = {}
    if slot in ("boots", "glove", "body"):
        filters["armour_filters"] = {"filters": {"ev": {"min": 1}}}
    if slot == "boots":
        stats[0]["filters"] += [SF(SHAPER), SF(MOVE_SPEED, 30)]
        stats.append({"type": "count", "value": {"min": 1},
                      "filters": [SF(i, 9) for i in CDR_IDS]})
    elif slot == "glove":
        stats.append({"type": "count", "value": {"min": 1},
                      "filters": [SF(i) for i in TEMPLE_IDS.values()]})
    elif slot == "body":
        misc["corrupted"] = {"option": "false"}
        stats.append({"type": "not", "filters": [SF(i) for i in BODY_LIFE_BAN]})
    else:                                     # ring1 / ring2
        misc["corrupted"] = {"option": "false"}
        misc["mirrored"] = {"option": "false"}
        # A free prefix for the "-# to Total Mana Cost of Skills" bench craft:
        # either an empty one, or an existing crafted prefix we can wipe.
        stats.append({"type": "count", "value": {"min": 1},
                      "filters": [SF(EMPTY_PREFIX, 1), SF(CRAFTED_PREFIX, 1)]})
        if slot == "ring2":
            stats[0]["filters"].append(SF(SHAPER))
    if misc:
        filters["misc_filters"] = {"filters": misc}
    if REQ_LVL_MAX:
        filters["req_filters"] = {"filters": {"lvl": {"max": REQ_LVL_MAX}}}
    return {"query": {"status": {"option": "securable"}, "stats": stats,
                      "filters": filters},
            "sort": {"price": "asc"}}


# ------------------------- parsing -------------------------
# POE1 mod texts are plain (no [A|B] wiki brackets) but are stripped defensively.
# Crafted mods arrive INSIDE explicitMods (flags.crafted / domain=="crafted");
# there is no craftedMods array.
#
# !! EVERY capture is SIGNED ([+-]), never a bare \+. Penalties are real and not
# rare: cached POE1 snapshots held "-60% to Lightning Resistance". A \+-anchored
# pattern reads those as ZERO, which OVERSTATES the combo's resistance and
# produces answers that silently miss the requirement.
_SIGNED = r"([+-]\d+)"

# A conditional/qualified line is NOT a flat grant. "+#% to Chaos Resistance when
# on Low Life", "+# to maximum Life per Level", "Minions have +#% to all
# Elemental Resistances" all match the bare patterns below and would be counted
# as if the character always had them.
#
# !! THE GUARD IS EVALUATED ON THE WHOLE DESCRIPTION; SCORING IS PER LINE.
# Measured across all 17325 rows of ../poe1/references/stats.tsv (2026-09-05):
# 2025 stat texts carry an embedded newline, in two OPPOSITE shapes, so neither
# "always split" nor "always join" is correct.
#
#   A. one stat whose sentence is merely WRAPPED:
#        "Inflict Fire Exposure on Hit against Enemies with"
#        "5 Cinderflame, applying #% to Fire Resistance"
#      Split, the second line reaches the resistance regex as if the CHARACTER
#      had it -- the qualifier lives on the first line.
#   B. one stat that BUNDLES two independent effects:
#        "+7% to Chaos Resistance"
#        "Minions deal 1 to 3 additional Chaos Damage"
#      Joined, "Minions" would suppress a resistance the character really has.
#      !! THIS SHAPE DOES NOT EXIST IN THE LIVE GAME. Its only instance in the
#      whole table is `crucible.mod_28602`, and the CRUCIBLE MECHANIC HAS BEEN
#      REMOVED (user, 2026-09-05). The `crucible` group is dead data the site
#      never cleaned out of its filter definitions.
#
# So guarding on the join is simply CORRECT here -- there is no live counter-
# example to trade against. Audited over the whole table 2026-09-05:
#   * 2025 rows carry a newline, but 1682 are `crucible` -- removed mechanic,
#     ignore. That leaves 343, all of them in gear-bearing groups;
#   * of those 343, 56 have a second line that starts a new statement (shape B
#     candidates) and ZERO carry a flat life / resistance / attribute that these
#     regexes score. They are flask double-immunities, "Players have ..." map
#     duplicates and multi-line trigger text;
#   * exactly ONE row matches the scoring patterns at all,
#     explicit.stat_3403551644 -- the Cinderflame line above, i.e. shape A.
#
# !! Any "how many rows in the whole table" statistic must exclude `crucible`
# first. Not doing so inflated this very count by 6x (2025 vs 343).
#
# Shape C -- one AFFIX granting several SEPARATE stats (the temple glove hybrid)
# -- has nothing to do with newlines. See the affix bookkeeping in _scan_mods().
COND_RE = re.compile(r"\b(when|while|during|if|per|against|Minions?|Totems?|"
                     r"Allies|Enemies|Nearby)\b")

# (regex, {axis: weight}, mod GROUP). The group is what makes same-colour
# exclusivity checkable: an item that already has `res_fire` natively can never
# take the bench's single-fire craft, but `res_fire_cold` is a different group
# and remains available (../poe1/knowledge/crafting.md, user 2026-09-05).
RES_MODS = [
    (_SIGNED + r"% to Fire Resistance", {"fire": 1}, "res_fire"),
    (_SIGNED + r"% to Cold Resistance", {"cold": 1}, "res_cold"),
    (_SIGNED + r"% to Lightning Resistance", {"light": 1}, "res_light"),
    (_SIGNED + r"% to Chaos Resistance", {"chaos": 1}, "res_chaos"),
    (_SIGNED + r"% to all Elemental Resistances",
     {"fire": 1, "cold": 1, "light": 1}, "res_all"),
    (_SIGNED + r"% to Fire and Cold Resistances", {"fire": 1, "cold": 1}, "res_fire_cold"),
    (_SIGNED + r"% to Fire and Lightning Resistances", {"fire": 1, "light": 1}, "res_fire_light"),
    (_SIGNED + r"% to Cold and Lightning Resistances", {"cold": 1, "light": 1}, "res_cold_light"),
    (_SIGNED + r"% to Fire and Chaos Resistances", {"fire": 1, "chaos": 1}, "res_fire_chaos"),
    (_SIGNED + r"% to Cold and Chaos Resistances", {"cold": 1, "chaos": 1}, "res_cold_chaos"),
    (_SIGNED + r"% to Lightning and Chaos Resistances", {"light": 1, "chaos": 1}, "res_light_chaos"),
]
# "+42 to Strength and Dexterity" is caught by the bare "to Strength" substring,
# so no hybrid row is needed for strength. Strength is scored only because
# pseudo_total_life counts Strength//2 -- it is not a constraint here.
OTHER_MODS = [
    (_SIGNED + r" to maximum Life", {"life": 1}),
    (_SIGNED + r" to maximum Energy Shield", {"es_mod": 1}),
    (_SIGNED + r" to Strength", {"str": 1}),
    (_SIGNED + r" to all Attributes", {"str": 1}),
]
MOD_KEYS = ("life", "es_mod", "str", "fire", "cold", "light", "chaos")
AXES = ("life", "fire", "cold", "light", "chaos")

# Any mod line mentioning Life disqualifies a BODY ARMOUR outright -- see the
# module docstring. Strength does not mention Life and is explicitly allowed by
# the user, so it survives this test and still feeds pseudo_total_life.
BODY_LIFE_RE = re.compile(r"\bLife\b", re.I)

MOVE_RE = re.compile(_SIGNED.replace("[+-]", "[+-]?") + r"% increased Movement Speed")
CDR_RE = re.compile(r"(\d+)% increased Cooldown Recovery Rate")


def _clean(s):
    return re.sub(r"\[([^\[\]|]*\|)?([^\[\]]*)\]", r"\2", s).strip()


NEGATIVE_RE = re.compile(r"^\s*-\d")
# Penalties do not all start with a minus sign, and `reduced` is not always bad
# ("reduced Enemy Stun Threshold" is an upside). Never auto-classify these --
# print them verbatim in the deliverable and let the buyer judge.
REDUCED_RE = re.compile(r"\d+% (reduced|less) ")
STRUCTURAL_RE = re.compile(r"Modifiers? allowed|to maximum Sockets|"
                           r"Implicit Modifiers Cannot Be Changed")


def _negative_class(text):
    if STRUCTURAL_RE.search(text):
        return "structural"
    for pat, _k, _g in RES_MODS:
        if re.search(pat, text):
            return "modelled"
    for pat, _k in OTHER_MODS:
        if re.search(pat, text):
            return "modelled"
    return "unmodelled"


def _load_banned():
    """Build-specific ban list, chosen by the user AFTER seeing `negatives`.

    Empty by default -- the script must never decide this on its own, and a list
    chosen for one build does not transfer to another. It lives in WORKDIR next
    to the pools so a new request starts with an empty one.
    """
    p = os.path.join(WORKDIR, "banned_mods.json")
    if os.path.isfile(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            return d.get("patterns", []) if isinstance(d, dict) else d
        except Exception:
            pass
    return []


BANNED_MODS = []
AFFIX_ALLOWED_RE = re.compile(r"([+-]\d+) (Prefix|Suffix) Modifiers? allowed")
MAX_AFFIX_DEFAULT = 3


def _scan_mods(item):
    """-> dict of everything parse_item() needs out of the mod lines.

    !! The crafted contribution is tracked on EVERY axis, not just resistance. An
    item holds one bench craft, so putting a resistance craft on it REMOVES
    whatever craft is already there along with all of that mod's stats. Tracking
    only crafted RESISTANCE let the ES sibling keep a crafted "+13 to Strength
    and Intelligence" while ALSO adding +35% fire to the same slot, and the
    delivered combo missed its strength requirement outright.

    Minion/totem/ally lines are skipped: "Minions have +11% to all Elemental
    Resistances" is a real Bone Ring implicit and is not the character's.
    """
    d = dict.fromkeys(MOD_KEYS, 0)
    craft_all = dict.fromkeys(MOD_KEYS, 0)
    affix_units = {}
    native_groups, craft_groups = set(), set()
    craft_defence = False
    affixes, texts = set(), []
    for key in ("implicitMods", "explicitMods", "craftedMods", "fracturedMods",
                "enchantMods"):
        for m in item.get(key) or []:
            obj = isinstance(m, dict)
            text = _clean(m if not obj else m.get("description", ""))
            texts.append(text)
            is_crafted = bool(obj and (m.get("domain") == "crafted"
                                       or (m.get("flags") or {}).get("crafted")))
            if is_crafted and re.search(r"Energy Shield|Evasion Rating|to Armour",
                                        text):
                craft_defence = True
            # Guard on the WHOLE description, score PER LINE -- see COND_RE.
            lines = [l.strip() for l in re.split(r"[\r\n]+", text) if l.strip()]
            # Which AFFIX this description belongs to. Two descriptions that
            # share a (name, tier) pair are ONE modifier -- measured 2026-09-05
            # on a temple glove: "+46% to Lightning Resistance" and "54%
            # increased Critical Strike Chance against Shocked Enemies" both
            # report mods=[('of Puhuarte','S0')]. This is the only reliable way
            # to know which display lines move together; `hybrid_res` below is
            # what turns it into something the caller can act on.
            akey = tuple(sorted((sub.get("name"), sub.get("tier")) for sub
                                in ((m.get("mods") or []) if obj else [])
                                if sub.get("tier")))
            unit = affix_units.setdefault((akey, is_crafted), {
                "names": [n for n, _t in akey], "tiers": [t for _n, t in akey],
                "crafted": is_crafted, "axes": dict.fromkeys(MOD_KEYS, 0),
                "groups": set(), "scored_lines": 0, "other_lines": 0})
            if COND_RE.search(" ".join(lines)):
                unit["other_lines"] += len(lines)
            else:
                for line in lines:
                    hit = False
                    for pat, keys, group in RES_MODS:
                        mm = re.search(pat, line)
                        if not mm:
                            continue
                        hit = True
                        val = int(mm.group(1))
                        for k, w in keys.items():
                            d[k] += val * w
                            unit["axes"][k] += val * w
                            if is_crafted:
                                craft_all[k] += val * w
                        unit["groups"].add(group)
                        (craft_groups if is_crafted else native_groups).add(group)
                    for pat, keys in OTHER_MODS:
                        mm = re.search(pat, line)
                        if not mm:
                            continue
                        hit = True
                        val = int(mm.group(1))
                        for k, w in keys.items():
                            d[k] += val * w
                            unit["axes"][k] += val * w
                            if is_crafted:
                                craft_all[k] += val * w
                    unit["scored_lines" if hit else "other_lines"] += 1
            for sub in ((m.get("mods") or []) if obj else []):
                tier = sub.get("tier") or ""
                if tier:
                    affixes.add((sub.get("name"), tier, is_crafted))
    native_suffix = len({a for a in affixes if a[1].startswith("S") and not a[2]})
    native_prefix = len({a for a in affixes if a[1].startswith("P") and not a[2]})
    # Single-element resistances that share ONE modifier with some other stat.
    # Horticrafting recolours a MODIFIER, so it drags these along
    # (../poe1/knowledge/horticrafting.md): recolour it and this many points
    # LEAVE the old element. The unconstrained optimum once picked a cold-temple
    # glove whose +46% cold was exactly this, and "buy any colour and convert"
    # would have dropped cold from 80 to 34 against a requirement of 58. With
    # this field that trap is data, not something a human has to spot by eye.
    SINGLE = {"res_fire": "fire", "res_cold": "cold", "res_light": "light"}
    hybrid_res = []
    for u in affix_units.values():
        if u["crafted"] or not u["other_lines"]:
            continue
        for grp, axis in SINGLE.items():
            if grp in u["groups"] and u["axes"][axis]:
                hybrid_res.append({"affix": "/".join(u["names"]) or "?",
                                   "tier": "/".join(u["tiers"]) or "?",
                                   "axis": axis, "value": u["axes"][axis]})
    return {"tot": d, "craft": craft_all, "native_groups": native_groups,
            "craft_groups": craft_groups, "craft_defence": craft_defence,
            "native_suffix": native_suffix, "native_prefix": native_prefix,
            "hybrid_res": hybrid_res, "texts": texts}


def _affix_cap(texts, kind):
    """How many prefixes/suffixes this item may hold at all.

    Normally 3. Reflecting-Mist (mirrored) items carry "-2 Suffix Modifiers
    allowed" style implicits; assuming a flat 3 made the ES sibling hand a
    resistance craft to an item with no room for it. Rings here are filtered to
    non-mirrored, but body/gloves/boots are not, so the check stays.
    """
    cap = MAX_AFFIX_DEFAULT
    for t in texts:
        m = AFFIX_ALLOWED_RE.search(t)
        if m and m.group(2) == kind:
            cap += int(m.group(1))
    return max(cap, 0)


def _prop(item, name):
    for p in item.get("properties") or []:
        if p.get("name") == name:
            try:
                return int(str(p["values"][0][0]).split()[0])
            except Exception:
                return None
    return None


def parse_item(it, qid, slot):
    """Listing -> candidate row, or None if the listing is unusable.

    Three hard rejections happen here rather than in the search query, because
    the search cannot express them reliably:
      * unknown currency (would be mis-priced),
      * a user-banned mod,
      * ANY Life modifier on a body armour (the Life Mastery condition).
    """
    item, lst = it["item"], it.get("listing") or {}
    s = _scan_mods(item)
    d, mods = s["tot"], s["texts"]
    p = lst.get("price") or {}
    if p.get("currency") not in RATES:
        return None
    for pat in BANNED_MODS:
        if any(re.search(pat, t) for t in mods):
            return None
    if slot == "body" and any(BODY_LIFE_RE.search(t) for t in mods):
        return None
    ext = item.get("extended") or {}
    move = max([int(m) for m in MOVE_RE.findall(" || ".join(mods))] or [0])
    cdr = max([int(m) for m in CDR_RE.findall(" || ".join(mods))] or [0])
    temple = [c for c, rx in TEMPLE_RE.items() if any(rx.search(t) for t in mods)]
    craft = s["craft"]
    row = {"id": item["id"], "qid": qid, "hash": it["id"], "slot": slot,
           "name": f"{item.get('name') or ''} {item.get('baseType') or ''}".strip(),
           "ilvl": item.get("ilvl"), "corrupt": bool(item.get("corrupted")),
           # POE1 marks a MIRRORED item as `duplicated`, NOT `mirrored`.
           "mirrored": bool(item.get("duplicated")),
           "influences": item.get("influences") or {},
           "suffix_cap": _affix_cap(mods, "Suffix"),
           "prefix_cap": _affix_cap(mods, "Prefix"),
           "native_suffix": s["native_suffix"], "native_prefix": s["native_prefix"],
           "native_groups": sorted(s["native_groups"]),
           "craft_groups": sorted(s["craft_groups"]),
           "craft_defence": s["craft_defence"], "hybrid_res": s["hybrid_res"],
           "negatives": [t for t in mods if NEGATIVE_RE.match(t)],
           # pseudo_total_life convention: flat life + Strength//2
           "life": d["life"] + d["str"] // 2, "flat": d["life"], "str": d["str"],
           # ES has two mutually exclusive sources and mixing them is the classic
           # scoring trap (../poe1/knowledge/slots.md): on ARMOUR it is the item's
           # ES defence in extended.es (local flat-ES is already baked in, so
           # parsing the mod text as well would double count); on JEWELLERY there
           # is no extended.es at all and "+# to maximum Energy Shield" is global.
           # ES is not scored here, only reported -- but a wrong number in the
           # deliverable is still a wrong number.
           "es": (int(ext.get("es") or 0) if slot not in RING_SLOTS
                  else d["es_mod"]),
           "ev": int(ext.get("ev") or 0), "ar": int(ext.get("ar") or 0),
           "fire": d["fire"], "cold": d["cold"], "light": d["light"],
           "chaos": d["chaos"],
           "craft_mod": craft, "move": move, "cdr": cdr, "temple": temple,
           "price": round(p["amount"] * RATES[p["currency"]], 3),
           "raw": f"{p['amount']} {p['currency']}",
           "seller": (lst.get("account") or {}).get("name", "?"), "mods": mods}
    if slot in RING_SLOTS:
        # The ring's ONE bench craft is reserved for "-# to Total Mana Cost of
        # Skills", so whatever craft it carries now goes away. Subtract the whole
        # contribution, and RECOMPUTE life -- pseudo life folds in Strength//2 and
        # integer division does not distribute over subtraction.
        row["flat"] -= craft["life"]
        row["str"] -= craft["str"]
        row["life"] = row["flat"] + row["str"] // 2
        for a in RES_AXES:
            row[a] -= craft[a]
        row["es"] = max(0, row["es"] - craft["es_mod"])
        row["craft_stripped"] = any(craft[k] for k in MOD_KEYS)
    return row


def score_of(items):
    """Total pseudo life. Integer, so numpy can stay in int32/int64."""
    return sum(i["life"] for i in items)


# ------------------------- ceiling probes -------------------------
# Count-only (`total`), no fetch -- cheap on the rate limit. >200 = conditions
# too soft, ~0 = too hard (../common/tricks.md). The first row of every slot is
# the bare hard-requirement query: that number IS the slot's supply ceiling, and
# for boots/gloves it is expected to be small.
PROBE = {
    "boots": [[], [(TOT_RES, 40)], [(TOT_RES, 70)], [(TOT_CHAOS, 25)],
              [(TOT_CHAOS, 35)], [(TOT_LIFE, 80)], [(TOT_LIFE, 100)],
              [(TOT_LIFE, 80), (TOT_RES, 40)]],
    "glove": [[], [(TOT_RES, 40)], [(TOT_RES, 70)], [(TOT_CHAOS, 25)],
              [(TOT_CHAOS, 35)], [(TOT_LIFE, 80)], [(TOT_LIFE, 100)],
              [(TOT_LIFE, 80), (TOT_RES, 40)]],
    "body":  [[], [(TOT_RES, 70)], [(TOT_RES, 100)], [(TOT_RES, 130)],
              [(TOT_CHAOS, 30)], [(TOT_CHAOS, 45)],
              [(TOT_CHAOS, 30), (TOT_RES, 70)], [(TOT_CHAOS, 45), (TOT_RES, 60)]],
    "ring1": [[], [(TOT_LIFE, 90)], [(TOT_LIFE, 110)],
              [(TOT_CHAOS, 30)], [(TOT_CHAOS, 45)],
              [(TOT_CHAOS, 30), (TOT_LIFE, 90)], [(TOT_CHAOS, 30), (TOT_RES, 60)],
              [(TOT_CHAOS, 45), (TOT_LIFE, 80)], [(TOT_RES, 110)]],
    "ring2": [[], [(TOT_LIFE, 90)], [(TOT_CHAOS, 30)],
              [(TOT_CHAOS, 30), (TOT_LIFE, 80)], [(TOT_RES, 90)]],
}
# The two same-text Cooldown Recovery ids, measured one at a time so the answer
# gets written down instead of guessed.
PROBE_CDR = {"cdrA_only": CDR_IDS[0], "cdrB_only": CDR_IDS[1]}


_SLUG = {TOT_LIFE: "life", TOT_RES: "ele", TOT_FIRE: "fire", TOT_COLD: "cold",
         TOT_LIGHT: "lght", TOT_CHAOS: "chaos"}


def _tag(stats):
    # !! Do NOT slug by the id's trailing word: pseudo_total_elemental_resistance
    # and pseudo_total_chaos_resistance both end in "resistance", so an
    # abbreviation collides and two different probes overwrite each other's
    # cache file. Explicit table instead.
    return "_".join(f"{_SLUG.get(sid, sid[-6:])}{v}" for sid, v in stats) or "bare"


def cmd_probe():
    for slot, rows in PROBE.items():
        for stats in rows:
            http_search(f"probe_{slot}_{_tag(stats)}",
                        slot_query(slot, [SF(s, v) for s, v in stats]))
    # Which CDR id is the real boots mod? Same query, one id each.
    for name, sid in PROBE_CDR.items():
        body = slot_query("boots", [])
        body["query"]["stats"] = [g for g in body["query"]["stats"]
                                  if g["type"] != "count"]
        body["query"]["stats"][0]["filters"].append(SF(sid, 9))
        http_search(f"probe_boots_{name}", body)
    # Sanity: does the shaper pseudo actually filter? Boots WITHOUT it.
    body = slot_query("boots", [])
    body["query"]["stats"][0]["filters"] = [
        f for f in body["query"]["stats"][0]["filters"] if f["id"] != SHAPER]
    http_search("probe_boots_noshaper", body)


# ------------------------- pools -------------------------
POOLS = {}
POOL_SLOT = {}


def define_pools(spec):
    POOLS.clear(); POOL_SLOT.clear()
    for name, v in spec.items():
        POOLS[name] = v
        POOL_SLOT[name] = v[0]


# (slot, [(stat_id, min), ...]).  Thresholds are refined from the probe counts;
# the bare pool of each slot is always kept because for boots and gloves the
# hard requirements alone already cut supply to a handful.
#
# Thresholds set from the 2026-09-05 probe counts, never guessed. Two facts
# shaped this list:
#   * BOOTS ARE THE SCARCE SLOT. Shaper + evasion base + MS>=30 + CDR>=9 returns
#     67 listings IN THE WHOLE LEAGUE (120 without the shaper requirement), so
#     one bare pool deep-fetched to 100 covers the entire market and every
#     narrower boots pool would be a strict subset of it.
#   * Everything else is supply-bound at the cheap end. A pool whose `total` hits
#     the 10000 cap, fetched price-ascending, returns 30 pieces of junk -- the
#     thresholds below are set so the CHEAPEST end of each pool is already
#     useful, which is the whole point of probing first (../common/tricks.md).
POOL_SPEC = {
    # 67 listings exist; `deep` pulls the whole search window.
    "boots_all":      ("boots", []),

    "glove_ele70":    ("glove", [(TOT_RES, 70)]),
    "glove_ele100":   ("glove", [(TOT_RES, 100)]),
    "glove_chaos20":  ("glove", [(TOT_CHAOS, 20)]),
    "glove_chaos30":  ("glove", [(TOT_CHAOS, 30)]),
    "glove_life100":  ("glove", [(TOT_LIFE, 100)]),
    "glove_life120":  ("glove", [(TOT_LIFE, 120)]),
    "glove_l80c20":   ("glove", [(TOT_LIFE, 80), (TOT_CHAOS, 20)]),
    "glove_l80e70":   ("glove", [(TOT_LIFE, 80), (TOT_RES, 70)]),

    # Body carries NO life modifier, so its only life contribution is
    # Strength//2 -- a TOT_LIFE threshold on this slot is really a strength
    # threshold, which is exactly what "body_str*" asks for.
    "body_ele100":    ("body",  [(TOT_RES, 100)]),
    "body_ele130":    ("body",  [(TOT_RES, 130)]),
    "body_chaos30":   ("body",  [(TOT_CHAOS, 30)]),
    "body_chaos45":   ("body",  [(TOT_CHAOS, 45)]),
    "body_c30e70":    ("body",  [(TOT_CHAOS, 30), (TOT_RES, 70)]),
    "body_c20e100":   ("body",  [(TOT_CHAOS, 20), (TOT_RES, 100)]),
    "body_str":       ("body",  [(TOT_LIFE, 25)]),
    "body_str_e70":   ("body",  [(TOT_LIFE, 20), (TOT_RES, 70)]),

    "ring1_c45l80":   ("ring1", [(TOT_CHAOS, 45), (TOT_LIFE, 80)]),
    "ring1_c55":      ("ring1", [(TOT_CHAOS, 55)]),
    "ring1_c35e60":   ("ring1", [(TOT_CHAOS, 35), (TOT_RES, 60)]),
    "ring1_c25e80":   ("ring1", [(TOT_CHAOS, 25), (TOT_RES, 80)]),
    "ring1_life130":  ("ring1", [(TOT_LIFE, 130)]),
    "ring1_l110e60":  ("ring1", [(TOT_LIFE, 110), (TOT_RES, 60)]),
    "ring1_ele130":   ("ring1", [(TOT_RES, 130)]),
    "ring1_c30l100":  ("ring1", [(TOT_CHAOS, 30), (TOT_LIFE, 100)]),

    "ring2_chaos25":  ("ring2", [(TOT_CHAOS, 25)]),
    "ring2_chaos35":  ("ring2", [(TOT_CHAOS, 35)]),
    "ring2_life90":   ("ring2", [(TOT_LIFE, 90)]),
    "ring2_life110":  ("ring2", [(TOT_LIFE, 110)]),
    "ring2_ele90":    ("ring2", [(TOT_RES, 90)]),
    "ring2_c20l70":   ("ring2", [(TOT_CHAOS, 20), (TOT_LIFE, 70)]),

    # ---- round 2 ----------------------------------------------------------
    # Round 1 stopped at 568 life while leaving 1500c of the budget UNSPENT,
    # i.e. the answer was supply-bound, not budget-bound, and every slot was
    # already sitting at its pool's life ceiling. More budget only helps if
    # there are listings that carry life AND chaos on the same item, so round 2
    # aims squarely at that frontier instead of at either axis alone.
    "ring1_l120c25":  ("ring1", [(TOT_LIFE, 120), (TOT_CHAOS, 25)]),
    "ring1_l130c15":  ("ring1", [(TOT_LIFE, 130), (TOT_CHAOS, 15)]),
    "ring1_l140":     ("ring1", [(TOT_LIFE, 140)]),
    "ring1_c65":      ("ring1", [(TOT_CHAOS, 65)]),
    "ring2_l120c15":  ("ring2", [(TOT_LIFE, 120), (TOT_CHAOS, 15)]),
    "ring2_l100c30":  ("ring2", [(TOT_LIFE, 100), (TOT_CHAOS, 30)]),
    "ring2_l130":     ("ring2", [(TOT_LIFE, 130)]),
    "ring2_c45":      ("ring2", [(TOT_CHAOS, 45)]),
    "glove_l130c15":  ("glove", [(TOT_LIFE, 130), (TOT_CHAOS, 15)]),
    "glove_l140":     ("glove", [(TOT_LIFE, 140)]),
    "glove_l120e70":  ("glove", [(TOT_LIFE, 120), (TOT_RES, 70)]),
    "body_str35":     ("body",  [(TOT_LIFE, 35)]),
    "body_c45s20":    ("body",  [(TOT_CHAOS, 45), (TOT_LIFE, 20)]),
    "body_chaos55":   ("body",  [(TOT_CHAOS, 55)]),

    # ---- round 3: push the per-slot LIFE ceiling ---------------------------
    # Round 2 landed on 626 = almost exactly the sum of each slot's best life in
    # the cached pools, so the answer is pinned by the pools' life ceiling, not
    # by the joint constraints. These ask directly for the top of each slot.
    "ring1_l150":     ("ring1", [(TOT_LIFE, 150)]),
    "ring1_l150c15":  ("ring1", [(TOT_LIFE, 150), (TOT_CHAOS, 15)]),
    "ring2_l140":     ("ring2", [(TOT_LIFE, 140)]),
    "ring2_l140c10":  ("ring2", [(TOT_LIFE, 140), (TOT_CHAOS, 10)]),
    "glove_l150":     ("glove", [(TOT_LIFE, 150)]),
    "glove_l140c20":  ("glove", [(TOT_LIFE, 140), (TOT_CHAOS, 20)]),
    "body_c40s15":    ("body",  [(TOT_CHAOS, 40), (TOT_LIFE, 15)]),
    "body_c35s20":    ("body",  [(TOT_CHAOS, 35), (TOT_LIFE, 20)]),

    # ---- round 4: the pools with >100 listings were only sampled at their
    # CHEAP end, so their life ceiling was never seen. Ask above it directly.
    "ring1_l160":     ("ring1", [(TOT_LIFE, 160)]),
    "ring1_l170":     ("ring1", [(TOT_LIFE, 170)]),
    "ring1_l160c15":  ("ring1", [(TOT_LIFE, 160), (TOT_CHAOS, 15)]),
    "ring2_l150":     ("ring2", [(TOT_LIFE, 150)]),
    "glove_l160":     ("glove", [(TOT_LIFE, 160)]),
    "glove_l150c15":  ("glove", [(TOT_LIFE, 150), (TOT_CHAOS, 15)]),
}
define_pools(POOL_SPEC)


def cmd_pools(force=False):
    for name, (slot, stats) in POOLS.items():
        run_pool(name, slot_query(slot, [SF(s, v) for s, v in stats]), force=force)


def cmd_deep(upto=100):
    """Extend every cached pool to `upto` listings WITHOUT re-searching.

    A search response stores a window of up to 100 result hashes and results are
    price-ascending, so hashes [30:100] are the same query's more expensive
    tranche (../common/tricks.md). Worth it exactly when the budget binds.
    """
    for name in POOLS:
        sf = os.path.join(WORKDIR, f"s_{name}.json")
        pf = os.path.join(WORKDIR, f"parsed_{name}.json")
        if not (os.path.exists(sf) and os.path.exists(pf)):
            print(f"{name:28s} skip (run `pools` first)")
            continue
        s, d = json.load(open(sf)), json.load(open(pf))
        have = {r["id"] for r in d["rows"]}
        # Derive the to-do list by DIFFING hashes, not by slicing from len(rows):
        # rows can be fewer than hashes consumed (sold / unknown currency / a
        # body armour rejected for carrying a life mod), and slicing would
        # silently re-fetch or skip.
        done = {r.get("hash") for r in d["rows"]}
        hashes = [h for h in (s.get("result") or [])[:upto] if h not in done]
        if not hashes:
            print(f"{name:28s} already deep ({len(d['rows'])} rows)")
            continue
        added = 0
        for i in range(0, len(hashes), FETCH_CAP):
            if transport() == "http":
                j = req(FETCH_URL.format(ids=",".join(hashes[i:i + FETCH_CAP]),
                                         qid=s["id"]))
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
        save_json(pf, d)
        ps = [r["price"] for r in d["rows"]] or [0]
        print(f"{name:28s} +{added:>3} -> {len(d['rows']):>3} rows  "
              f"price {min(ps):.0f}-{max(ps):.0f}c", flush=True)


def cmd_negatives(top=60):
    """Classify every negative/`reduced` mod in the cached pools and ASK.

    Nothing is banned by default and the classifier is a heuristic, not a
    semantic judgement -- "-# Lightning Damage taken from Hits" starts with a
    minus and is a GOOD thing. Human review is the point of this command.
    """
    from collections import Counter
    seen = Counter()
    where = {}
    for fn in sorted(glob.glob(os.path.join(WORKDIR, "parsed_*.json"))):
        d = json.load(open(fn))
        slot = POOLS.get(d.get("name", ""), (None,))[0]
        for r in d.get("rows", []):
            for t in r.get("mods") or []:
                if NEGATIVE_RE.match(t) or REDUCED_RE.search(t):
                    key = re.sub(r"[+-]?\d+(\.\d+)?", "#", t)
                    seen[key] += 1
                    where.setdefault(key, set()).add(slot)
    groups = {"unmodelled": [], "modelled": [], "structural": []}
    for k, n in seen.most_common(top):
        groups[_negative_class(k)].append((k, n, sorted(where[k])))
    for g in ("unmodelled", "modelled", "structural"):
        print(f"\n===== {g} ({len(groups[g])}) =====")
        for k, n, sl in groups[g]:
            print(f"  {n:>4}x {'/'.join(sl):18s} {k}")
    print("\nBans go in", os.path.join(WORKDIR, "banned_mods.json"),
          '-> {"patterns": ["regex", ...]}')


# ------------------------- bench crafting -------------------------
# ../poe1/knowledge/crafting.md. One crafted mod per item; resistance crafts are
# suffixes, so the item must be uncorrupted with a free suffix. Rolls are
# re-rollable at near-zero cost, so value them at the tier maximum.
#
# There is NO pure-chaos bench craft -- chaos comes from the element+chaos
# hybrids (15/15) or natively. The all-elemental craft (12x3) is JEWELLERY ONLY
# and the rings are barred from crafting here anyway, so it does not appear.
CRAFT_OPTIONS = [
    ("火+35", {"fire": 35}, "res_fire"),
    ("冰+35", {"cold": 35}, "res_cold"),
    ("雷+35", {"light": 35}, "res_light"),
    ("火冰+20", {"fire": 20, "cold": 20}, "res_fire_cold"),
    ("火雷+20", {"fire": 20, "light": 20}, "res_fire_light"),
    ("冰雷+20", {"cold": 20, "light": 20}, "res_cold_light"),
    ("火混+15", {"fire": 15, "chaos": 15}, "res_fire_chaos"),
    ("冰混+15", {"cold": 15, "chaos": 15}, "res_cold_chaos"),
    ("雷混+15", {"light": 15, "chaos": 15}, "res_light_chaos"),
]


def has_free_suffix(c):
    """Can a resistance suffix still be bench-crafted onto this listing?

    Blockers: corrupted, MIRRORED (`duplicated` in the API -- permanently frozen,
    a second seal independent of corruption), and suffix slots already full. The
    cap is not always 3: Reflecting-Mist items carry "-2 Suffix Modifiers
    allowed" implicits. An existing CRAFTED suffix is reclaimable, so only native
    suffixes count.
    """
    if c["slot"] not in CRAFT_SLOTS:
        return False
    ns = c.get("native_suffix")
    if ns is None or c.get("corrupt") or c.get("mirrored"):
        return False
    return ns < c.get("suffix_cap", MAX_AFFIX_DEFAULT)


def craftable(c):
    return bool(CRAFT) and has_free_suffix(c)


def craft_potential(c):
    return 1 if (has_free_suffix(c) and not c.get("craft")) else 0


def expand_crafts(cands):
    """Add one virtual candidate per resistance craft the item could carry.

    Two rules that the older siblings get wrong or skip:
      * applying a craft REPLACES the craft already on the item, so EVERY axis
        that craft contributed comes back off first -- not just resistance;
      * a craft whose MOD GROUP is already present natively is impossible. An
        item with a native "+40% to Fire Resistance" cannot take the bench's
        +35% fire; offering it produces a combo that cannot be built.
    Life is recomputed rather than adjusted (Strength//2, integer division).
    """
    out = []
    for c in cands:
        out.append(dict(c, craft=None))
        if not craftable(c):
            continue
        cm = c.get("craft_mod") or {}
        flat = c["flat"] - cm.get("life", 0)
        st = c["str"] - cm.get("str", 0)
        base = {a: c[a] - cm.get(a, 0) for a in RES_AXES}
        taken = set(c.get("native_groups") or [])
        for label, delta, group in CRAFT_OPTIONS:
            if group in taken:
                continue
            row = dict(c, craft=label, flat=flat, str=st, life=flat + st // 2)
            for a in RES_AXES:
                row[a] = base[a] + delta.get(a, 0)
            out.append(row)
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
    save_json(p, sorted(cur))
    return cur


def load():
    """Pools -> per-slot candidate lists.

    Rings are pooled JOINTLY and split afterwards: a shaper ring that turned up
    in a ring1 pool is a perfectly good ring2 candidate, and throwing it away
    because of which query found it would waste fetch quota. ring2 keeps only
    listings whose `influences.shaper` is set; ring1 keeps everything.
    """
    excl = sold_ids()
    by_slot = {s: {} for s in SLOT_ORDER}
    rings = {}
    for fn in sorted(glob.glob(os.path.join(WORKDIR, "parsed_*.json"))):
        d = json.load(open(fn))
        slot = POOLS.get(d.get("name", ""), (None,))[0]
        if slot is None:
            continue
        for r in d.get("rows", []):
            if r["id"] in excl or r["price"] > BUDGET:
                continue
            # Re-apply the ban list here too: pools cached BEFORE the user chose
            # their bans were parsed without them.
            if BANNED_MODS and any(re.search(p, t) for p in BANNED_MODS
                                   for t in (r.get("mods") or [])):
                continue
            if (slot == "glove" and TEMPLE_ONLY
                    and TEMPLE_ONLY not in (r.get("temple") or [])):
                continue
            r = dict(r, pool=d["name"])
            tgt = rings if slot in RING_SLOTS else by_slot[slot]
            old = tgt.get(r["id"])
            if old is None or r["price"] < old["price"]:
                tgt[r["id"]] = r
    for r in rings.values():
        # A ring's one bench craft is reserved for -mana cost, so it needs a
        # prefix slot that is free or reclaimable. The search filter says so
        # already; re-check locally because pools get reused across edits.
        if r.get("native_prefix", 0) >= r.get("prefix_cap", MAX_AFFIX_DEFAULT):
            continue
        by_slot["ring1"][r["id"]] = dict(r, slot="ring1")
        if (r.get("influences") or {}).get("shaper"):
            by_slot["ring2"][r["id"]] = dict(r, slot="ring2")
    return {k: list(v.values()) for k, v in by_slot.items()}


def pareto(cands):
    """Drop a candidate if another is at most as expensive and at least as good
    on EVERY axis (life + 4 resistances) plus craft potential."""
    out = []
    for c in sorted(cands, key=lambda c: (c["price"], -c["life"])):
        if not any(all(k[a] >= c[a] for a in AXES)
                   and craft_potential(k) >= craft_potential(c)
                   and k["price"] <= c["price"] for k in out):
            out.append(c)
    return out


def thin(cands, k):
    """Keep the EXTREMES of every axis the optimizer trades off, not the top-k of
    one ranking -- that would throw away exactly the pieces a constraint needs.
    Craftable leaders get their own rankings: their on-item resistance is low BY
    DESIGN, so every other ordering buries them."""
    if len(cands) <= k:
        return cands
    n = max(4, k // 6)
    keep, seen = [], set()
    rankings = [lambda c: -c["life"],
                lambda c: -c["fire"], lambda c: -c["cold"],
                lambda c: -c["light"], lambda c: -c["chaos"],
                lambda c: -(c["fire"] + c["cold"] + c["light"] + c["chaos"]),
                lambda c: -(c["chaos"] * 2 + c["cold"]),
                lambda c: -c["life"] / max(c["price"], 0.5),
                lambda c: -(c["fire"] + c["cold"] + c["light"] + c["chaos"])
                / max(c["price"], 0.5),
                lambda c: (c["price"], -c["life"]),
                lambda c: (-craft_potential(c), -c["life"]),
                lambda c: (-craft_potential(c), c["price"])]
    for key in rankings:
        for c in sorted(cands, key=key)[:n]:
            if c["id"] not in seen:
                seen.add(c["id"])
                keep.append(c)
    return keep


def prep(pools):
    """pareto -> thin on PHYSICAL listings, THEN expand craft options.

    Order matters (measured on the life-only task): expanding first makes ~10
    virtual candidates per listing and eats thin()'s budget with variants of a
    few items instead of a diverse set -- it scored BELOW the no-craft run, which
    is impossible on the merits (../poe1/knowledge/crafting.md).
    """
    p = {k: pareto(v) for k, v in pools.items()}
    if FAST:
        p = {k: thin(v, FAST) for k, v in p.items()}
    return {k: pareto(expand_crafts(v)) for k, v in p.items()}


# ------------------------- optimizer -------------------------
# Pick one listing per slot maximising total life subject to FOUR joint minimums
# (fire/cold/lightning/chaos) and a total price cap, with the two rings forced to
# be different listings.
#
#   1. CLAMP every aggregate at the requirement on all four axes. Surplus is
#      worth nothing, so the state space is finite and small.
#   2. Per clamped state keep only the price/score PARETO frontier. Lossless --
#      a query only ever asks "best score at >= X, price <= Y".
#   3. Join the two halves by a VECTORISED scan with exact upper bounds.
# selftest() cross-checks the whole thing against a 5-nested-loop brute force.
PRICE_BIN = 1.0     # chaos. Aggregates are deduped per this bucket; at a 4200c
                    # budget a 0.05c bucket would make dedup useless. Bucketing
                    # only merges near-equal prices; the real per-combo price is
                    # what gets checked downstream.


def clamp_key(v, cap):
    return tuple(min(v[i], cap[i]) for i in range(NAX))


# !! The clamp ceiling is NOT `need`. Clamping at `need` is only sound while every
# aggregate is non-negative, and POE1 listings carry real penalties ("-60% to
# Lightning Resistance"). Once one half goes negative on an axis, the OTHER half
# must supply MORE than `need` to compensate -- but it too was clamped at `need`,
# so it can never express the surplus and a feasible, often optimal, combo is
# silently dropped. Caught by the ES sibling's selftest in 2026-08: brute force
# 314602 vs solver 293722.
def slot_minima(cands):
    if not cands:
        return (0,) * NAX
    return tuple(min(c[a] for c in cands) for a in RES_AXES)


def _cap(need, *others):
    """need + how negative the slots NOT yet folded in could go, per axis.

    Two properties this must keep, both learned by breaking them:
      * cap >= need ALWAYS. solve() derives its deficit as `need - ak`, which
        assumes ak was never clamped below the true value; a tighter ceiling
        overstates the deficit and returns None on a feasible problem.
      * sum each remaining slot's NEGATIVE reach separately, not the reach of
        their sum -- netting a slot that can go -13 against one that always gives
        +20 makes the intermediate clamp lossy again.
    """
    return tuple(need[i] + sum(max(0, -o[i]) for o in others) for i in range(NAX))


def frontier(groups):
    """Per clamped state keep only the price/score Pareto frontier.

    !! The running maximum starts at None, NOT at -1 or 0. Scores can be
    NEGATIVE: a ring carrying "-131 to maximum Life" scores below zero, and
    against a 0 sentinel `score > best` is false on the very first entry, so the
    whole state is discarded and solve() returns None on a solvable problem.
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

    `cap` is the clamp ceiling for the slot set AFTER folding in `right`.
    """
    best = {}
    for lp, ls, lk, litems in left:
        for c in right:
            p = round(lp + c["price"], 3)
            if p > BUDGET:
                continue
            k = clamp_key([lk[i] + c[RES_AXES[i]] for i in range(NAX)], cap)
            sc = ls + c["life"]
            dk = (k, int(p / PRICE_BIN))
            cur = best.get(dk)
            if cur is None or sc > cur[1] or (sc == cur[1] and p < cur[0]):
                best[dk] = (p, sc, k, litems + (c,))
    return frontier(list(best.values()))


def ring_pairs(r1, r2, cap):
    """Ordered ring pairs, skipping any pair that is the SAME LISTING twice.

    This is the one structural difference from the siblings: two slots draw from
    one category, so a naive cross-product would happily "buy" one ring and wear
    it on both hands. ring2 is the shaper-influenced subset; ring1 is everything,
    so a shaper ring can legitimately appear on either side -- just not on both
    at once with the same listing id.
    """
    best = {}
    for a in r1:
        for b in r2:
            if a["id"] == b["id"]:
                continue
            p = round(a["price"] + b["price"], 3)
            if p > BUDGET:
                continue
            k = clamp_key([a[RES_AXES[i]] + b[RES_AXES[i]] for i in range(NAX)], cap)
            sc = a["life"] + b["life"]
            dk = (k, int(p / PRICE_BIN))
            cur = best.get(dk)
            if cur is None or sc > cur[1] or (sc == cur[1] and p < cur[0]):
                best[dk] = (p, sc, k, (a, b))
    return frontier(list(best.values()))


def build_halves(p, need):
    zero = [(0.0, 0, (0,) * NAX, ())]
    mB, mG = slot_minima(p["boots"]), slot_minima(p["glove"])
    mBody = slot_minima(p["body"])
    mR1, mR2 = slot_minima(p["ring1"]), slot_minima(p["ring2"])
    capB = _cap(need, mG, mBody, mR1, mR2)     # boots alone
    capBG = _cap(need, mBody, mR1, mR2)        # boots + glove
    capA = _cap(need, mR1, mR2)                # boots + glove + body
    capJ = _cap(need, mB, mG, mBody)           # ring1 + ring2
    A = combine(combine(combine(zero, p["boots"], capB), p["glove"], capBG),
                p["body"], capA)
    J = ring_pairs(p["ring1"], p["ring2"], capJ)
    return A, J


def _arrays(G):
    return (np.array([g[0] for g in G]),
            np.array([g[1] for g in G], dtype=np.int64),
            np.array([[*g[2]] for g in G], dtype=np.int32))


def _axis_major(k):
    """(N,NAX) row-major states -> (NAX,N) axis-major, narrowed to int16 when it
    fits. The mask compares ONE axis at a time; a row-major column walk discards
    most of every cache line it pulls in. Measured on the sibling's real data:
    1.019ms -> 0.371ms from the transpose, -> 0.261ms from int16, and the working
    set halves, which is the difference between fitting in L3 or not."""
    lo, hi = int(k.min()), int(k.max())
    dtype = (np.int16 if np.iinfo(np.int16).min < lo and hi < np.iinfo(np.int16).max
             else np.int32)
    return np.ascontiguousarray(k.T, dtype=dtype)


def solve(A, J, budget, need):
    """max score over A x J meeting `need` within `budget`. Exact for the given
    candidate sets."""
    if not A or not J:
        return None
    ap, asc, ak = _arrays(A)
    jp, jsc, jk = _arrays(J)
    # J is deliberately NOT sorted: the vectorised scan needs no ordering, and an
    # earlier sibling version returned J[k] using a SORTED index, silently handing
    # back a different listing than the one that satisfied the mask.
    needv = np.array(need, dtype=np.int32)
    jmaxp = float(jp.max())
    jscmax = int(jsc.max())
    # Per-axis floor of J. Used to skip an axis mask ONLY when it is provably
    # always satisfied. The tempting test `if deficit > 0` is WRONG because J can
    # be NEGATIVE on an axis, and that failure mode is UNSAFE: it returns combos
    # that miss the requirement.
    jkmin = jk.min(axis=0)
    jkT = _axis_major(jk)
    jsc_argmax = int(np.argmax(jsc))
    ge_lo, ge_tab, ge_best = [], [], []
    for a in range(NAX):
        row = jkT[a]
        lo, hi = int(row.min()), int(row.max())
        cnt = np.bincount((row - lo).astype(np.int64), minlength=hi - lo + 1)
        ge_lo.append(lo)
        ge_tab.append(np.cumsum(cnt[::-1])[::-1].astype(np.int64).copy())
        order = np.argsort(row, kind="stable")
        vals, sc = row[order], jsc[order]
        sufmax = np.maximum.accumulate(sc[::-1])[::-1]
        first = np.searchsorted(vals, np.arange(lo, hi + 1), side="left")
        ge_best.append(np.where(first < vals.size,
                                sufmax[np.minimum(first, vals.size - 1)],
                                np.iinfo(np.int64).min).copy())

    def _count_ge(a, d):
        off = d - ge_lo[a]
        if off <= 0:
            return jp.size
        tab = ge_tab[a]
        return int(tab[off]) if off < tab.size else 0

    def _best_ge(a, d):
        off = d - ge_lo[a]
        if off <= 0:
            return jscmax
        tab = ge_best[a]
        return int(tab[off]) if off < tab.size else np.iinfo(np.int64).min

    porder = np.argsort(jp, kind="stable")
    jp_sorted = jp[porder]
    jsc_prefmax = np.maximum.accumulate(jsc[porder])
    best = None
    for i in np.argsort(-asc, kind="stable"):
        if ap[i] > budget:
            continue
        if best is not None and int(asc[i]) + jscmax < best[0]:
            break
        rem = budget - ap[i]
        if best is not None:
            aff = np.searchsorted(jp_sorted, rem + 1e-9, side="right") - 1
            if aff < 0 or int(asc[i]) + int(jsc_prefmax[aff]) < best[0]:
                continue
        deficit = needv - ak[i]
        constrained = []
        axis_bound = jscmax
        for axis in range(NAX):
            if deficit[axis] <= jkmin[axis]:
                continue                      # provably satisfied by every J
            d = int(deficit[axis])
            constrained.append((_count_ge(axis, d), axis))
            b = _best_ge(axis, d)
            if b < axis_bound:
                axis_bound = b
        if best is not None and int(asc[i]) + axis_bound < best[0]:
            continue
        cand = None
        if constrained:
            constrained.sort()                # fewest survivors first
            if constrained[0][0] == 0:
                continue
            for n, (_cnt, axis) in enumerate(constrained):
                row = jkT[axis]
                cand = (np.nonzero(row >= deficit[axis])[0] if n == 0
                        else cand[row[cand] >= deficit[axis]])
                if cand.size == 0:
                    break
            if cand.size == 0:
                continue
        if cand is None:
            if rem >= jmaxp:
                k = jsc_argmax
                tot = int(asc[i]) + int(jsc[k])
                if best is None or tot > best[0] or (tot == best[0]
                                                     and ap[i] + jp[k] < best[3]):
                    best = (tot, int(i), int(k), float(ap[i] + jp[k]))
                continue
            cand = np.arange(jp.size)
        # price filtered LAST, on the narrowed set, in float64 so the 1e-9
        # tolerance keeps its meaning at four-figure chaos prices
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
    return {"score": tot["life"], "life": tot["life"],
            "price": round(sum(i["price"] for i in items), 3),
            "es": sum(i["es"] for i in items), "ev": sum(i["ev"] for i in items),
            "res": tot, "items": items}


def needs(margin=None):
    margin = MARGIN if margin is None else margin
    return tuple(n + margin for n in NEED)


def cmd_solve(margin=None, tiers=None, quiet=False):
    need = needs(margin)
    p = prep(load())
    if not quiet:
        print(f"need F{need[0]} C{need[1]} L{need[2]} CHAOS{need[3]}"
              f"{'  FAST=' + str(FAST) if FAST else '  EXACT'}  craft={CRAFT}")
        print("candidates:", {k: len(v) for k, v in p.items()}, flush=True)
    t0 = time.time()
    A, J = build_halves(p, need)
    if not quiet:
        eta = len(A) * len(J) / _ETA_GROUPS_PER_SEC
        print(f"groups A={len(A)} J={len(J)}  ({time.time()-t0:.1f}s)", flush=True)
        print(f"ETA for all {len(tiers or TIERS)} tiers: ~{eta/60:.1f} min", flush=True)
    out = {}
    rf = os.path.join(WORKDIR, os.environ.get("POE_RESULT", "result.json"))
    for b in (tiers or TIERS):
        t1 = time.time()
        r = solve(A, J, float(b), need)
        if not r:
            print(f"[<= {b:g}c] no feasible combo  ({time.time()-t1:.0f}s)", flush=True)
            continue
        s = summarize(*r)
        out[tkey(b)] = {"budget": b, "margin": MARGIN if margin is None else margin, **s}
        # Write after EVERY tier: cost grows steeply with budget, so the
        # expensive tiers come last and a kill used to throw away the cheap ones.
        save_json(rf, out, indent=1)
        print(f"\n[<= {b:g}c] LIFE={s['life']}  spend={s['price']:.2f}c  "
              f"F{s['res']['fire']} C{s['res']['cold']} L{s['res']['light']} "
              f"CH{s['res']['chaos']}  ({time.time()-t1:.0f}s)", flush=True)
        if not quiet:
            for i in s["items"]:
                cr = f" 工藝:{i['craft']}" if i.get("craft") else ""
                print(f"   {i['slot']:6s} {i['raw']:>14s} L{i['life']:>4} "
                      f"F{i['fire']:>3} C{i['cold']:>3} L{i['light']:>3} "
                      f"CH{i['chaos']:>4}  {i['name'][:28]:28s} "
                      f"@{i['seller']} [{i['pool']}]{cr}", flush=True)
    save_json(rf, out, indent=1)
    print(f"\ntotal solve time {time.time()-t0:.1f}s", flush=True)
    return out


# ------------------------- selftest -------------------------
def _row(mods, slot="body", **kw):
    it = {"id": kw.pop("id", "x"), "item": {"id": kw.pop("iid", "x"),
          "explicitMods": [m if isinstance(m, dict) else {"description": m}
                           for m in mods], **kw},
          "listing": {"price": {"amount": 1, "currency": "chaos"},
                      "account": {"name": "a#1"}}}
    return parse_item(it, "q", slot)


def selftest_parse():
    """Parsing is where a silent off-by-one hides. Pin down the cases that have
    actually bitten, plus the ones this script introduces."""
    bad = 0

    def chk(name, got, want):
        nonlocal bad
        for k, v in want.items():
            if got is None or got.get(k) != v:
                print(f"  PARSE FAIL {name}: {k}={None if got is None else got.get(k)} "
                      f"want {v}")
                bad += 1

    chk("chaos single", _row(["+35% to Chaos Resistance"]), {"chaos": 35})
    chk("chaos hybrid", _row(["+24% to Cold and Chaos Resistances"]),
        {"cold": 24, "chaos": 24})
    # "maximum Chaos Resistance" is a DIFFERENT stat and must not be read as res
    chk("max chaos not res", _row(["+5% to maximum Chaos Resistance"]), {"chaos": 0})
    # conditional grants are not flat grants
    # NB: slot must not be "body" for these -- the body armour gate rejects any
    # listing whose mod text mentions Life, which would mask the parse result.
    chk("conditional", _row(["+30% to Chaos Resistance when on Low Life"],
                            slot="boots"), {"chaos": 0})
    chk("minion line", _row(["Minions have +11% to all Elemental Resistances"]),
        {"fire": 0})
    # penalties must be SIGNED, not read as zero
    chk("negative res", _row(["-60% to Lightning Resistance"]), {"light": -60})
    chk("all ele", _row(["+16% to all Elemental Resistances"]),
        {"fire": 16, "cold": 16, "light": 16})
    chk("life + str", _row(["+100 to maximum Life", "+41 to Strength"],
                           slot="boots"), {"life": 120, "flat": 100, "str": 41})
    chk("str hybrid", _row(["+42 to Strength and Dexterity"], slot="boots"),
        {"str": 42, "life": 21})
    # --- the three multi-line / multi-stat shapes, modelled on real API data ---
    #
    # C. The temple hybrid is ONE affix rendered as TWO SEPARATE descriptions
    #    that share a (name, tier). Measured 2026-09-05: both halves report
    #    mods=[('of Puhuarte','S0')]. The earlier version of this test modelled
    #    it as a single newline-joined description, which is NOT what the API
    #    sends -- a test encoding the wrong wire format proves nothing.
    temple = _row([{"description": "49 to 75 added Fire Damage against Burning Enemies",
                    "mods": [{"name": "of Tacati", "tier": "S0"}]},
                   {"description": "+46% to Fire Resistance",
                    "mods": [{"name": "of Tacati", "tier": "S0"}]}], slot="glove")
    chk("temple: separate descriptions, one affix", temple,
        {"fire": 46, "temple": ["fire"]})
    #    ... and the resistance must be flagged as LINKED, because horticrafting
    #    recolours the modifier and would drag all 46 points out of fire.
    if [(h["axis"], h["value"]) for h in (temple or {}).get("hybrid_res") or []] \
            != [("fire", 46)]:
        print("  PARSE FAIL temple hybrid_res:", (temple or {}).get("hybrid_res"))
        bad += 1
    #    A plain single-stat resistance suffix must NOT be flagged as linked.
    plain = _row([{"description": "+46% to Fire Resistance",
                   "mods": [{"name": "of the Volcano", "tier": "S1"}]}], slot="glove")
    if (plain or {}).get("hybrid_res"):
        print("  PARSE FAIL plain res wrongly flagged linked:", plain["hybrid_res"])
        bad += 1
    # --- affix COUNTING: display lines != affixes, in BOTH directions at once.
    #     Real item supplied by the user 2026-09-05 (Rage Wrap Conquest
    #     Lamellar): `Adaptable` P2 and `Crocodile's` P1 each render across two
    #     lines, while "+226 to maximum Life" is the MERGED total of `Prime` P1
    #     and `Crocodile's` P1. Six display lines, six affixes -- but 3 prefixes
    #     and 3 suffixes, i.e. FULL, no room for any bench craft. Eyeballing the
    #     lines would read this as having a free slot.
    merged = _row([
        {"description": "+418 to Armour",
         "mods": [{"name": "Adaptable", "tier": "P2"},
                  {"name": "Crocodile's", "tier": "P1"}]},
        {"description": "+292 to Evasion Rating",
         "mods": [{"name": "Adaptable", "tier": "P2"}]},
        {"description": "+226 to maximum Life",
         "mods": [{"name": "Prime", "tier": "P1"},
                  {"name": "Crocodile's", "tier": "P1"}]},
        {"description": "+55 to Strength",
         "mods": [{"name": "of the Gods", "tier": "S1"}]},
        {"description": "+50 to Dexterity",
         "mods": [{"name": "of the Phantom", "tier": "S2"}]},
        {"description": "22% increased Stun and Block Recovery",
         "mods": [{"name": "of Steel Skin", "tier": "S3"}]},
    ], slot="glove")
    #     !! `tier` alone is NOT a key: Crocodile's P1 and Prime P1 coexist.
    #     Deduping on tier would count 2 prefixes and declare a free slot.
    chk("merged display -> 3 prefixes / 3 suffixes", merged,
        {"native_prefix": 3, "native_suffix": 3})
    #     the merged life line is the correct total, and our pseudo-life
    #     convention reproduces the site's own number for this item (the user's
    #     search for it was pseudo_total_life 253-254): 226 + 55//2 = 253
    chk("merged life total matches the site's pseudo", merged, {"life": 253})
    if has_free_suffix(dict(merged, slot="glove")):
        print("  PARSE FAIL full item judged craftable")
        bad += 1
    #     implicits and lab enchants report mods=[(None, None)] and must not be
    #     counted as affixes -- they occupy no prefix/suffix slot.
    noise = _row([{"description": "+97 to maximum Life",
                   "mods": [{"name": "Rotund", "tier": "P2"}]}],
                 slot="ring1",
                 implicitMods=[{"description": "+25 to maximum Life",
                                "mods": [{"name": None, "tier": None}]}],
                 enchantMods=[{"description": "Allocates Twin Terrors",
                               "mods": [{"name": None, "tier": None}]}])
    chk("implicit/enchant do not inflate affix counts", noise,
        {"native_prefix": 1, "native_suffix": 0, "life": 122})
    # A. a WRAPPED sentence: the qualifier is on line 1, the number on line 2.
    #    Scoring line 2 alone would credit the character with a resistance that
    #    is actually applied to enemies. Only gear-bearing stat in the whole
    #    table with this shape that also matches our patterns.
    chk("wrapped sentence (Cinderflame)",
        _row(["Inflict Fire Exposure on Hit against Enemies with\n"
              "5 Cinderflame, applying -25% to Fire Resistance"], slot="boots"),
        {"fire": 0})
    # B. a BUNDLED stat: guarding on the join costs us the +7% chaos. Kept as a
    #    behavioural pin only -- this shape has NO live instance (its sole row is
    #    in the removed `crucible` group), so nothing real is being given up.
    chk("bundled stat, minion half suppresses (dead shape, pin only)",
        _row(["+7% to Chaos Resistance\n"
              "Minions deal 1 to 3 additional Chaos Damage"], slot="boots"),
        {"chaos": 0})
    # ... but a multi-line stat with NO qualifier anywhere must score every line.
    chk("multi-line, no qualifier -> both lines score",
        _row(["+60 to maximum Life\n+10% to all Elemental Resistances"],
             slot="boots"),
        {"flat": 60, "fire": 10, "cold": 10, "light": 10})
    # body armour: ANY Life modifier disqualifies (Life Mastery condition)
    if _row(["+100 to maximum Life", "+30% to Fire Resistance"], slot="body") is not None:
        print("  PARSE FAIL body life mod not rejected"); bad += 1
    if _row(["Regenerate 5 Life per second"], slot="body") is not None:
        print("  PARSE FAIL body life regen not rejected"); bad += 1
    if _row(["+40 to Strength", "+30% to Fire Resistance"], slot="body") is None:
        print("  PARSE FAIL body strength wrongly rejected"); bad += 1
    # rings: the existing craft is stripped, because its slot goes to -mana cost
    r = _row([{"description": "+30% to Fire Resistance", "domain": "crafted",
               "mods": [{"name": "of Craft", "tier": "S3"}]},
              {"description": "+80 to maximum Life",
               "mods": [{"name": "Hale", "tier": "P2"}]},
              {"description": "+29% to Chaos Resistance",
               "mods": [{"name": "of the Order", "tier": "S1"}]}], slot="ring1")
    chk("ring craft stripped", r, {"fire": 0, "chaos": 29, "life": 80})
    # ... and the same craft on an ARMOUR slot is kept until a craft replaces it
    a = _row([{"description": "+30% to Fire Resistance", "domain": "crafted",
               "mods": [{"name": "of Craft", "tier": "S3"}]}], slot="boots")
    chk("armour craft kept", a, {"fire": 30})
    # craft exclusivity: a native single-fire res blocks the single-fire craft
    n = _row([{"description": "+40% to Fire Resistance",
               "mods": [{"name": "of the Volcano", "tier": "S1"}]}], slot="boots")
    labels = {c["craft"] for c in expand_crafts([n]) if c.get("craft")}
    if "火+35" in labels:
        print("  PARSE FAIL single-fire craft offered on a native-fire item"); bad += 1
    if "火冰+20" not in labels:
        print("  PARSE FAIL dual fire/cold craft wrongly withheld"); bad += 1
    return bad


def _brute(sub, budget, need):
    bf = None
    for items in itertools.product(sub["boots"], sub["glove"], sub["body"],
                                   sub["ring1"], sub["ring2"]):
        if items[3]["id"] == items[4]["id"]:
            continue
        if round(sum(i["price"] for i in items), 3) > budget + 1e-9:
            continue
        if any(sum(i[key] for i in items) < nd
               for key, nd in zip(RES_AXES, need)):
            continue
        sc = score_of(items)
        if bf is None or sc > bf:
            bf = sc
    return bf


def cmd_selftest(k=7, seeds=12):
    """Cross-check solve() against a literal 5-nested-loop brute force on random
    subsets. Run after ANY optimizer edit -- an off-by-one in the clamp or a
    mis-ordered dedup produces plausible-but-wrong answers, not crashes.

    !! SAMPLE SIZE IS THE WHOLE TEST. A subset of k listings almost never
    satisfies the REAL requirement, so scaled-down requirement vectors are what
    actually exercise the clamp/frontier/join; the full vector is kept as the
    last (usually infeasible) row so the infeasible path is covered too. The
    sibling's one-seed version passed while the solver carried two real defects.
    """
    import random
    bad = selftest_parse()
    full = needs()
    pools = load()
    if any(len(v) < 2 for v in pools.values()):
        sys.exit("not enough candidates cached -- run `pools` first: "
                 + str({kk: len(v) for kk, v in pools.items()}))
    p = {kk: pareto(expand_crafts(v)) for kk, v in pools.items()}
    fails = tested = viol = 0
    for seed in range(1, seeds + 1):
        random.seed(seed)
        for scale in (0.0, 0.15, 0.3, 0.45, 0.6, 0.8, 1.0):
            need = tuple(int(round(n * scale)) for n in full)
            sub = {kk: random.sample(v, min(k, len(v))) for kk, v in p.items()}
            A, J = build_halves(sub, need)
            for budget in (100, 400, 1200, 2500, BUDGET):
                bf = _brute(sub, budget, need)
                res = solve(A, J, float(budget), need)
                got = None
                if res:
                    s = summarize(*res)
                    got = s["score"]
                    if s["price"] > budget + 1e-9:
                        print(f"  OVER BUDGET {s['price']}>{budget}"); viol += 1
                    if s["items"][3]["id"] == s["items"][4]["id"]:
                        print("  SAME RING TWICE"); viol += 1
                    for key, nd in zip(RES_AXES, need):
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


# ------------------- verification & buy links -------------------
_HASH_FETCH_JS = r"""
async page => await page.evaluate(async () => {
  const QID = __QID__, HASHES = __HASHES__;
  const r = await fetch('/api/trade/fetch/' + HASHES.join(',') + '?query=' + QID);
  if (!r.ok) return JSON.stringify({error: 'fetch ' + r.status});
  return JSON.stringify(await r.json());
})
"""

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
    """Seller + slot + a floor on whatever identifies the piece.

    The account name MUST keep its #1234 discriminator -- without it the search
    returns 0 SILENTLY (measured, ../poe1/QUERY.md). The life floor uses the
    candidate's CRAFT-STRIPPED life for rings, which is <= what the listing
    displays, so it stays a valid floor.
    """
    stats = []
    if it["life"] > 0:
        stats.append(SF(TOT_LIFE, it["life"]))
    filters = {"type_filters": {"filters": {"category": {"option": CAT[it["slot"]]},
                                            "rarity": {"option": RARITY}}},
               "trade_filters": {"filters": {"account": {"input": it["seller"]}}}}
    return {"query": {"status": {"option": "securable"},
                      "stats": [{"type": "and", "filters": stats}] if stats else [],
                      "filters": filters},
            "sort": {"price": "asc"}}


def _fetch_hashes(qid, hashes):
    """An empty hash list MUST short-circuit: /fetch/?query=... returns 404, and
    that is the common case (item sold -> seller search returns nothing)."""
    hashes = [h for h in (hashes or []) if h]
    if not hashes:
        return []
    if transport() == "http":
        j = req(FETCH_URL.format(ids=",".join(hashes), qid=qid))
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
               "life": res[tier]["life"], "price": res[tier]["price"],
               "es": res[tier]["es"], "ev": res[tier]["ev"],
               "res": res[tier]["res"], "items": out}
    save_json(os.path.join(WORKDIR, f"verified_{tier}.json"), payload, indent=1)
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
TEMPLE_ZH = {"fire": "火（Burning）", "cold": "冰（Chilled）", "light": "雷（Shocked）"}


def cmd_report(tiers=None, out_dir=None):
    tiers = [tkey(t) for t in (tiers or [TIERS[-1]])]
    solver_note = ("精確解（每部位候選全數納入，與 5 層暴力解對拍相符）" if not FAST else
                   f"瘦身模式 `POE_FAST={FAST}`（每部位保留約 {FAST} 個實體候選再展開工藝）。"
                   "⚠ 有損模式，**只會低估、不會給出買不到或不達標的組合**")
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
    shared = (set.intersection(*[{i["id"] for i in v["items"]} for v in vs])
              if len(vs) > 1 else set())

    L = [f"# POE1 配裝查詢結果 — 鞋子／手套／身體／雙戒（{LEAGUE}）", "",
         f"- **產生時間**：{time.strftime('%Y-%m-%d %H:%M')}",
         f"- **部位**：{'／'.join(ZH[s] for s in SLOT_ORDER)} 共 {len(SLOT_ORDER)} 件",
         f"- **預算**：{BUDGET:.0f} chaos（= 10 divine，1 div = {DIV:.2f}c，"
         "poe2scout /api/pc/Leagues 當日讀數）",
         f"- **抗性需求**：火 +{NEED[0]} / 冰 +{NEED[1]} / 雷 +{NEED[2]} / "
         f"**混沌 +{NEED[3]}**（緩衝 +{MARGIN}）",
         "- **目標函數**：在滿足全部硬約束下**最大化總生命**"
         "（`+# to maximum Life` + 力量÷2，即交易站的 pseudo 總生命口徑）",
         "- **每件的硬條件**：鞋＝Shaper／閃避底／移速≥30%／CDR≥9%；"
         "手套＝閃避底／神廟複合詞；身體＝閃避底／未腐化／**完全沒有任何 Life 詞綴**；"
         "戒指＝未腐化未鏡像／有空前綴或工藝前綴可讓給 -技能消耗；戒指2 另需 Shaper",
         "- **戒指抗性一律扣掉既有工藝詞綴**（那格要讓給 -6~-7 技能消耗，"
         "一件只能有一條工藝），所以表上的戒指數值就是「洗掉工藝之後」的實得值",
         f"- **限制**：{RARITY} 裝；不設需求等級上限；Instant Buyout（`securable`）",
         f"- **求解模式**：{solver_note}"
         + ("；**護甲三件含工藝補抗**（買後綴有空位的便宜貨自己上）" if CRAFT else ""),
         *([f"- **收斂階梯**：{ladder}"] if ladder else []), ""]

    for v in vs:
        def _carriers(key):
            return "／".join(f"{ZH[i['slot']]} {i[key]}" for i in sorted(
                v["items"], key=lambda x: -x[key]) if i[key] > 0) or "無"
        crafted = [i for i in v["items"] if i.get("craft")]
        craft_txt = ("；" + str(len(crafted)) + " 件靠工藝後綴補抗（"
                     + "、".join(f"{ZH[i['slot']]} {i['craft']}" for i in crafted)
                     + "）") if crafted else "；未動用工藝"
        gl = [i for i in v["items"] if i["slot"] == "glove"]
        t_txt = ""
        if gl and gl[0].get("temple"):
            cols = "／".join(TEMPLE_ZH.get(c, c) for c in gl[0]["temple"])
            t_txt = f"；手套神廟詞為 {cols}"
            if "fire" not in gl[0]["temple"]:
                t_txt += "（**非火色，要花園工藝轉換，約 50–70c/次**）"
        L += [f"## 方案：{v['price']:.1f}c，總生命 +{v['life']}", "",
              f"- **描述**：混沌抗由 {_carriers('chaos')} 扛"
              f"{craft_txt}{t_txt}。",
              f"- **總價格**：**{v['price']:.1f} chaos**（約 {v['price']/DIV:.2f} divine，"
              f"佔預算 {v['price']/BUDGET*100:.0f}%）",
              f"- **總生命**：**+{v['life']}**（另計天賦 %increased Life 加成；"
              "身體無 Life 詞綴，Life Mastery 的 15% 條件成立）",
              f"- **附帶防禦**：閃避 +{v['ev']}、能量護盾 +{v['es']}（未計入評分）",
              "- **需求檢核**：" + "｜".join(
                  f"{n} **{v['res'][k]}** / 需求 {nd}（{v['res'][k]-nd:+d}）"
                  for k, n, nd in zip(RES_AXES, ("火抗", "冰抗", "雷抗", "混沌抗"), NEED)),
              f"- **驗證在架**：{v['verified_at']} 逐件 hash fetch 確認"
              f"（{'全部 live' if all(i['live'] for i in v['items']) else '⚠ 部分已售出'}）",
              "",
              "| 部位 | 名稱 | 關鍵屬性 | 價格 | 購買連結 | 備註 |",
              "|---|---|---|---|---|---|"]
        for it in v["items"]:
            attr = (f"生命 **{it['life']}**（平擊 {it['flat']}"
                    + (f" + 力量 {it['str']}/2" if it["str"] else "") + "）"
                    + f"<br>火 {it['fire']} / 冰 {it['cold']} / 雷 {it['light']}"
                    + f" / **混沌 {it['chaos']}**"
                    + (f"<br>閃避 {it['ev']}" if it["ev"] else "")
                    + (f" ES {it['es']}" if it["es"] else ""))
            if it["slot"] == "boots":
                attr += f"<br>移速 {it['move']}%、CDR {it['cdr']}%"
            if it["slot"] == "glove" and it.get("temple"):
                attr += "<br>神廟詞：" + "／".join(TEMPLE_ZH.get(c, c)
                                                for c in it["temple"])
            note = []
            if it.get("craft"):
                note.append(f"**買回來上工藝：{it['craft']}**（已計入左欄抗性）")
            if it["slot"] in RING_SLOTS:
                note.append("**前綴留給 -6~-7 技能消耗工藝**")
                if it.get("craft_stripped"):
                    note.append("⚠ 這件現有工藝詞綴的貢獻已從左欄扣除")
            if it["id"] in shared:
                note.append("**多套共用同一件**")
            if it.get("corrupt"):
                note.append("已腐化（不能上工藝、不能園藝轉換）")
            if it.get("mirrored"):
                note.append("**Mirrored（複製品）——永久定型**")
            if it.get("negatives"):
                note.append("⚠ 負面詞綴：" + "、".join(f"`{t}`" for t in it["negatives"]))
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
    live_note = ("- **⚠ 上表有 " + str(len(dead)) + " 件在驗證當下已售出**（"
                 + "、".join(f"{ZH[i['slot']]} {i['name']}" for i in dead)
                 + "）。要實際採買請重跑一輪並 `converge` 到全部在架。"
                 ) if dead else (
                 "- **交付前已逐件確認全部在架**，但這個價位分鐘級售出，拖久仍可能失效。")
    L += ["## 通用注意事項", "",
          live_note,
          "- **購買連結是「賣家＋部位＋生命下限」的過濾搜尋**"
          "（帳號名含 `#1234`，缺了會靜靜回 0 筆）。連結失效就用備註的「同規格替代」。",
          "- **戒指買回來要自己上 `-# to Total Mana Cost of Skills` 工藝**；"
          "那是該戒指唯一的工藝格，所以表上的抗性已經預先扣掉既有工藝。",
          "- **護甲件的工藝抗性要自己上**（未腐化才行）。同一件只能一條工藝，"
          "而且同色單元素抗性互斥——求解器已排除「原生已有該色單抗」的組合。",
          "- **身體不可有任何 Life 詞綴**（Life Mastery 15% 條件）。"
          "求解時已在搜尋端與解析端各擋一次；買之前再確認一次物品說明沒有 Life 字樣。",
          "- 抗性缺口以 PoB 的 `MissingFireResist` 等欄位為準"
          f"（火 {NEED[0]}／冰 {NEED[1]}／雷 {NEED[2]}／混沌 {NEED[3]}，"
          "最大抗性 75%）。買齊後回 PoB 覆核一次。", ""]

    root = out_dir or os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                   "..", "..", "..", ".."))
    fn = os.path.join(root, f"search_results_{time.strftime('%Y%m%d%H%M')}.md")
    open(fn, "w", encoding="utf-8").write("\n".join(L))
    print("wrote", fn)
    return fn


# ------------------------- main -------------------------
def main():
    cmds = {"probe", "pools", "deep", "negatives", "solve", "verify",
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
