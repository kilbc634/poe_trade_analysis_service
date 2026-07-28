# -*- coding: utf-8 -*-
"""Multi-slot gear combo optimizer for POE1 /trade (多部位配裝聯合求解), 6-slot proven.

!! REALM: POE1 ONLY. Sibling of gear_combo_optimizer_poe2.py (POE2 ONLY).
!! The ALGORITHM is realm-agnostic; every endpoint path, filter field name, stat
!! id, currency and mod-text regex below was re-derived from ../poe1/QUERY.md and
!! ../poe1/references/stats.tsv. Do NOT copy any of it to the POE2 script and do
!! not assume a POE2 field name carries over -- a wrong-game stat id can be
!! SILENTLY VALID and return the wrong items instead of erroring.

Built and verified 2026-07-28 on Allflame against the real task
"buy 6 slots (helmet/gloves/amulet/ring x2/belt) within 30 chaos, cover
fire 129 / cold 62 / lightning 91, maximise total maximum-Life".

>> Writing a NEW optimizer? Record its layers / lossy point / runtime in
>> ../common/optimizer-algorithms.md (there is a fill-in template at the bottom)
>> so generations stay comparable on the axes that actually matter.

Differences from the POE2 script -- read these before assuming behaviour:
  * POE1 paths carry NO realm segment and NO ?realm= param.
  * Bundles verification + report generation (the POE2 side splits those into
    verify_links_poe2.py). One file, subcommands.
  * EXACT optimizer instead of lossy bucket pruning -- see solve().
  * Two transports: plain HTTP with a POESESSID, or in-page fetch through an
    already-logged-in headed browser when that cookie is dead (see TRANSPORT).

Pipeline (../common/tricks.md):
  probe -> pools -> solve -> verify -> converge -> report

  probe    ceiling probes per slot, reads `total` only (no fetch). Cheap.
  pools    per-slot searches at probe-derived thresholds, fetch + parse.
  solve    joint optimisation over the cross-product, per budget tier.
  verify   re-check every winning listing is still live; build buy links.
  converge verify -> drop sold -> re-solve, until every item is live.
  report   markdown deliverable per ../common/delivery.md.

Usage:
    python gear_combo_optimizer_poe1.py selftest      # brute-force check the solver FIRST
    python gear_combo_optimizer_poe1.py probe
    python gear_combo_optimizer_poe1.py pools
    python gear_combo_optimizer_poe1.py solve
    python gear_combo_optimizer_poe1.py converge      # the one you want after items sell
    python gear_combo_optimizer_poe1.py report
    POE_FAST=75 python ... solve                      # 40x faster re-solve, see thin()

Requires numpy (the 3-D suffix-max join). Everything else is stdlib.

MEASURED LESSONS, don't relearn them the hard way:
  * The market is far cheaper than intuition suggests. 1 chaos buys an L143 /
    73-total-res rare helmet. Do NOT anchor thresholds low "because the budget
    is small" -- my first 3 probe rounds (46 searches) were wasted that way.
    FETCH A DOZEN REAL ITEMS EARLY (`pools` on one loose pool) instead of
    creeping up with count-only probes; one fetch beat 46 probes.
  * At this price band the binding constraint is SUPPLY, not budget: raising the
    price cap 5c -> 10c barely moves the achievable spec (L200 helmets and L205
    belts are 0 listings at either). Per-slot life ceilings and the full probe
    grid are recorded in ../poe1/knowledge/slots.md -- READ IT AND SKIP PROBING.
  * Cheap gear sells in MINUTES. 5 items sold mid-session on the reference run.
    Always finish with `converge`, and deliver fast.
  * Do NOT put a literal-currency price cap on pool searches: it silently drops
    listings priced in exalted/chromatic/alch (POE1 exalted is only ~0.93c!).
    Use sort=price asc and filter on the real price locally.
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
    sys.exit("numpy required (3-D suffix-max join). pip install numpy")

# Windows consoles default to cp950 -> CJK seller names crash the final print
# stage AFTER all the network work is done. Force utf-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# =============================== CONFIG ===============================
# Read LEAGUE/REALM from setting.py; REALM must be poe1 or this script is wrong.
LEAGUE = "Allflame"
WORKDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gear_pools_poe1")

BUDGET = 30.0                       # chaos, the hard ceiling
NEED = (129, 62, 91)                # (fire, cold, lightning) resistance shortfall
MARGIN = 5                          # safety buffer added to NEED -- see note below
TIERS = (8, 10, 12, 15, 18, 20, 22, 25, 30)   # marginal-value curve, last = BUDGET
REQ_LVL_MAX = 75                    # character level; drops unwearable high bases
RARITY = "rare"
N_PER_POOL = 30                     # listings fetched per pool (price asc)

# Why MARGIN: the zero-buffer optimum lands on fire EXACTLY 129. That is 9-19
# more life for zero fault tolerance -- one sold listing or one misread mod and
# the build is under cap. Buffered is the recommendation; set MARGIN=0 to see the
# theoretical max.

# chaos-denominated. REFRESH ME: poe2scout /api/pc/Leagues + .../SnapshotPairs,
# see ../poe1/knowledge/exchange-rates.md. 1 div moved +19% in a single day and
# ~2% within one day, so anything cross-day must be re-fetched.
RATES = {"chaos": 1.0, "divine": 118.3763, "exalted": 0.934, "vaal": 0.5633,
         "alt": 0.1466, "fusing": 0.1883, "regal": 0.2089, "chance": 0.0734,
         "jewellers": 0.0422, "gcp": 2.7926, "blessed": 0.2279, "annul": 8.8485,
         "chrome": 1.4241, "scour": 0.3184, "alch": 0.0679, "regret": 0.6689,
         "transmute": 0.0085}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

# Slot -> trade category. `ring` is used twice (two distinct listings).
CAT = {"helm": "armour.helmet", "glove": "armour.gloves",
       "amu": "accessory.amulet", "ring": "accessory.ring", "belt": "accessory.belt"}
ZH = {"helm": "頭盔", "glove": "手套", "amu": "項鍊", "ring": "戒指", "belt": "腰帶"}
SLOT_ORDER = ["helm", "glove", "amu", "ring", "ring", "belt"]

# FAST: keep only N candidates per slot. Cheap gear sells in minutes, so a
# re-solve has to finish in seconds or its answer is stale too. Measured on the
# reference task (see thin() and ../common/tricks.md): 75 is 40x faster than
# exact AND returns the identical max-budget answer; mid tiers lose 5-8 life.
FAST = int(os.environ.get("POE_FAST", "0"))
# ======================================================================


def _load_poesessid():
    """POESESSID from setting.py (env-backed), walking up from this file."""
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
_auth_ok = None          # None = untested, True = Account rule seen, False = anon

# ------------------------- transport: plain HTTP -------------------------
# Endpoints (../poe1/QUERY.md, measured): NO realm segment, NO ?realm=.
SEARCH_URL = "https://www.pathofexile.com/api/trade/search/{league}"
FETCH_URL = "https://www.pathofexile.com/api/trade/fetch/{ids}?query={qid}"
RESULT_URL = "https://www.pathofexile.com/trade/search/{league}/{qid}"
FETCH_CAP = 10           # 11 hashes -> HTTP 400 "Invalid query". Confirmed POE1.


def _throttle_wait(hdrs):
    """Header-driven throttle. <Rule> = max:period:penalty,
    <Rule>-State = used:period:locked. Keep every window below its cap.
    NOTE these counters are a lenient DECOY for ANONYMOUS traffic (a hidden
    ~30-request quota fires a ~600s penalty with no headers at all); logging in
    is the actual fix. See ../common/tricks.md."""
    def parse(s):
        return [tuple(int(x) for x in t.split(":")) for t in s.split(",") if t]
    wait = 0
    for rule in [r.strip() for r in (hdrs.get("X-Rate-Limit-Rules") or "").split(",") if r.strip()]:
        lim, st = hdrs.get(f"X-Rate-Limit-{rule}"), hdrs.get(f"X-Rate-Limit-{rule}-State")
        if not lim or not st:
            continue
        for (mx, per, _pen), (cur, _p2, locked) in zip(parse(lim), parse(st)):
            if locked > 0:
                wait = max(wait, locked + 2)
            elif cur >= mx - 1:
                wait = max(wait, per)
    return wait


def req(url, data=None):
    global _auth_ok
    headers = {"User-Agent": UA}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if POESESSID:
        headers["Cookie"] = f"POESESSID={POESESSID}"
    r = urllib.request.Request(url, data=data, headers=headers)
    for _ in range(4):
        try:
            with urllib.request.urlopen(r) as resp:
                out = json.load(resp)
                if _auth_ok is None:
                    # Rules=Account,Ip means the cookie authenticated. Ip alone
                    # = anonymous pool (hidden quota, ~600s walls).
                    _auth_ok = "Account" in (resp.headers.get("X-Rate-Limit-Rules") or "")
                w = _throttle_wait(resp.headers)
                if w:
                    print(f"  rate-limit near cap -> waiting {w}s", flush=True)
                    time.sleep(w)
                return out
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = int(e.headers.get("Retry-After", "60"))
                print(f"  429 -> sleeping {ra+5}s (penalty blocks ALL trade endpoints)", flush=True)
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
    time.sleep(2)     # burst-guard floor; anti-rapid-click is invisible to headers
    return j


def http_pool(name, body, need):
    """search + fetch + parse over plain HTTP. Needs a live POESESSID."""
    s = http_search(name, body)
    qid, hashes = s["id"], (s.get("result") or [])[:need]
    rows = []
    for i in range(0, len(hashes), FETCH_CAP):
        j = req(FETCH_URL.format(ids=",".join(hashes[i:i + FETCH_CAP]), qid=qid))
        for it in (j.get("result") or []):
            if not it or it.get("gone"):
                continue
            row = parse_item(it, qid)
            if row:
                rows.append(row)
        time.sleep(1.5)
    return {"qid": qid, "total": s.get("total"), "rows": rows}


# ------------------ transport: in-page fetch (browser) ------------------
# When both the setting.py and .poe_cookies.json POESESSIDs are expired (they
# come back with Rules=Ip only) you do NOT need a fresh cookie: open the site
# with `playwright-cli open --headed --persistent`, confirm /api/profile == 200,
# and run every request IN-PAGE. Measured 2026-07-28: in-page requests report
# Rules=Account,Ip, i.e. they ride the logged-in pool, no cookie extraction.
#
# Two traps, both cost real time:
#  1. Pass the JS as a FILE (`run-code --filename`). As an argv string, cmd.exe
#     eats the literal % in the resistance regexes and the page throws
#     "SyntaxError: Unexpected token ')'" -- looks like broken JS, is a mangled
#     argument. (`eval --filename` means "save the RESULT to a file" -- different
#     flag, don't confuse them.)
#  2. npm's global shim is not a PE executable: subprocess needs
#     %APPDATA%\npm\playwright-cli.cmd or you get WinError 2.
# Parse IN-PAGE and return only compact rows -- the CLI's stdout lands in the
# agent's context, so never ship whole listing JSON back.
PW_EXE = os.path.expandvars(r"%APPDATA%\npm\playwright-cli.cmd")

_INPAGE_JS = r"""
async page => await page.evaluate(async () => {
  const LEAGUE = __LEAGUE__, BODY = __BODY__, NEED = __NEED__, RATES = __RATES__;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const clean = s => s.replace(/\[([^\[\]|]*\|)?([^\[\]]*)\]/g, '$2');
  const PATS = __PATS__;
  const throttle = async (h) => {
    const parse = s => (s||'').split(',').filter(Boolean).map(t => t.split(':').map(Number));
    let wait = 0;
    for (const rule of (h.get('X-Rate-Limit-Rules')||'').split(',').filter(Boolean)) {
      const lim = parse(h.get('X-Rate-Limit-' + rule.trim()));
      const st  = parse(h.get('X-Rate-Limit-' + rule.trim() + '-State'));
      for (let i = 0; i < Math.min(lim.length, st.length); i++) {
        if (st[i][2] > 0) wait = Math.max(wait, st[i][2] + 2);
        else if (st[i][0] >= lim[i][0] - 1) wait = Math.max(wait, lim[i][1]);
      }
    }
    if (wait) await sleep(wait * 1000);
  };
  const sr = await fetch('/api/trade/search/' + encodeURIComponent(LEAGUE),
    {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(BODY)});
  if (!sr.ok) return JSON.stringify({error:'search '+sr.status, body:(await sr.text()).slice(0,200)});
  const s = await sr.json();
  const qid = s.id, hashes = (s.result || []).slice(0, NEED);
  await throttle(sr.headers); await sleep(2000);
  const rows = [];
  for (let i = 0; i < hashes.length; i += 10) {          // POE1 fetch cap = 10
    const fr = await fetch('/api/trade/fetch/' + hashes.slice(i, i+10).join(',') + '?query=' + qid);
    if (fr.status === 429) { await sleep((parseInt(fr.headers.get('Retry-After')||'60')+5)*1000); i -= 10; continue; }
    if (!fr.ok) return JSON.stringify({error:'fetch '+fr.status, qid, got:rows.length});
    const j = await fr.json();
    await throttle(fr.headers);
    for (const it of (j.result || [])) {
      if (!it || it.gone) continue;
      const item = it.item, lst = it.listing || {};
      const mods = [];
      for (const k of ['implicitMods','explicitMods','craftedMods','fracturedMods','enchantMods']) {
        for (const m of (item[k] || [])) mods.push(clean(typeof m === 'string' ? m : (m.description || '')));
      }
      const d = {life:0, str:0, fire:0, cold:0, light:0};
      for (const line of mods) for (const [src, keys] of PATS) {
        const mm = line.match(new RegExp(src));
        if (mm) for (const k of keys) d[k] += parseInt(mm[1]);
      }
      const p = lst.price || {};
      if (!(p.currency in RATES)) continue;
      rows.push({id:item.id, qid, name:((item.name||'') + ' ' + (item.baseType||'')).trim(),
                 ilvl:item.ilvl, corrupt:!!item.corrupted,
                 life:d.life + Math.floor(d.str/2), flat:d.life, str:d.str,
                 fire:d.fire, cold:d.cold, light:d.light,
                 price:Math.round(p.amount * RATES[p.currency] * 1000)/1000,
                 raw:p.amount + ' ' + p.currency,
                 seller:(lst.account||{}).name || '?', mods});
    }
    await sleep(1500);
  }
  return JSON.stringify({qid, total:s.total, rows});
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
        return json.loads(json.loads(out))      # --raw prints a JSON string literal
    except Exception:
        raise RuntimeError(f"unparseable playwright output: {out[:300]}")


def browser_pool(name, body, need):
    js = (_INPAGE_JS.replace("__LEAGUE__", json.dumps(LEAGUE))
                    .replace("__BODY__", json.dumps(body))
                    .replace("__NEED__", str(need))
                    .replace("__RATES__", json.dumps(RATES))
                    .replace("__PATS__", json.dumps([[p, k] for p, k in MOD_PATTERNS])))
    d = _playwright(js, f"pool_{name}")
    if "error" in d:
        raise RuntimeError(f"{name}: {d}")
    return d


def transport():
    """'http' if the POESESSID authenticates, else 'browser'.
    Anonymous HTTP is deliberately NOT used for fetching: its hidden ~30-request
    quota fires ~600s penalties with no warning headers."""
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
    """Cached per-pool search+fetch+parse via whichever transport works."""
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
# Stat ids: pseudo group uses NAMED ids. Freshly grepped from
# ../poe1/references/stats.tsv -- never reuse an id from memory or from POE2.
TOT_LIFE = "pseudo.pseudo_total_life"          # = flat life + Strength/2
TOT_RES = "pseudo.pseudo_total_elemental_resistance"
TOT_FIRE = "pseudo.pseudo_total_fire_resistance"
TOT_COLD = "pseudo.pseudo_total_cold_resistance"
TOT_LIGHT = "pseudo.pseudo_total_lightning_resistance"


def SF(sid, mn):
    return {"id": sid, "value": {"min": mn}, "disabled": False}


def q(category, stat_filters, price_max=None, lvl_max=REQ_LVL_MAX, rarity=RARITY):
    """POE1 query body. status/sort live at the root, NOT inside filters.

    price_max uses the LITERAL-chaos mode, which compares real amounts but only
    matches chaos-priced listings -- fine for counting during `probe`, WRONG for
    pools (it hides exalted/chromatic/alch-priced items). Leave it None for pools.
    """
    filters = {"type_filters": {"filters": {"category": {"option": category}}}}
    if rarity:
        filters["type_filters"]["filters"]["rarity"] = {"option": rarity}
    if lvl_max:
        filters["req_filters"] = {"filters": {"lvl": {"max": lvl_max}}}
    if price_max is not None:
        filters["trade_filters"] = {"filters": {"price": {"option": "chaos", "max": price_max}}}
    return {"query": {"status": {"option": "securable"},      # Instant Buyout
                      "stats": [{"type": "and", "filters": stat_filters}],
                      "filters": filters},
            "sort": {"price": "asc"}}


# ------------------------- parsing -------------------------
# POE1 mod texts, verified against ../poe1/references/stats.tsv. Plain text --
# no [A|B] wiki brackets (unlike POE2) -- but stripped defensively anyway.
# Crafted mods arrive INSIDE explicitMods (flags.crafted / domain=="crafted");
# there is NO craftedMods array. Entries may be strings OR objects with
# .description, so handle both.
#
# Ordering matters: the dual-res lines must NOT be matched by the single-res
# patterns. "+16% to Fire and Cold Resistances" does not match
# "+#% to Fire Resistance" (different trailing text), so plain alternation is
# safe -- but keep the anchors intact if you edit these.
MOD_PATTERNS = [
    (r"\+(\d+) to maximum Life", ["life"]),
    # A single "to Strength" pattern also catches "Strength and Intelligence" /
    # "Strength and Dexterity" hybrids, each counted once -- which is correct.
    (r"\+(\d+) to Strength", ["str"]),
    (r"\+(\d+) to all Attributes", ["str"]),
    (r"\+(\d+)% to Fire Resistance", ["fire"]),
    (r"\+(\d+)% to Cold Resistance", ["cold"]),
    (r"\+(\d+)% to Lightning Resistance", ["light"]),
    (r"\+(\d+)% to all Elemental Resistances", ["fire", "cold", "light"]),
    (r"\+(\d+)% to Fire and Cold Resistances", ["fire", "cold"]),
    (r"\+(\d+)% to Fire and Lightning Resistances", ["fire", "light"]),
    (r"\+(\d+)% to Cold and Lightning Resistances", ["cold", "light"]),
    # "X and Chaos" duals: the chaos half is ignored on purpose (chaos res is
    # out of scope for this task's constraints).
    (r"\+(\d+)% to Fire and Chaos Resistances", ["fire"]),
    (r"\+(\d+)% to Cold and Chaos Resistances", ["cold"]),
    (r"\+(\d+)% to Lightning and Chaos Resistances", ["light"]),
]
MOD_KEYS = ("life", "str", "fire", "cold", "light")


def _clean(s):
    return re.sub(r"\[([^\[\]|]*\|)?([^\[\]]*)\]", r"\2", s)


def parse_item(it, qid):
    """fetch result -> normalized candidate row (same shape as the in-page JS)."""
    item, lst = it["item"], it.get("listing") or {}
    mods = []
    for k in ("implicitMods", "explicitMods", "craftedMods", "fracturedMods", "enchantMods"):
        for m in item.get(k) or []:
            mods.append(_clean(m if isinstance(m, str) else m.get("description", "")))
    d = dict.fromkeys(MOD_KEYS, 0)
    for line in mods:
        for pat, keys in MOD_PATTERNS:
            mm = re.search(pat, line)
            if mm:
                for k in keys:
                    d[k] += int(mm.group(1))
    p = lst.get("price") or {}
    if p.get("currency") not in RATES:
        return None
    return {"id": item["id"], "qid": qid,
            "name": f"{item.get('name') or ''} {item.get('baseType') or ''}".strip(),
            "ilvl": item.get("ilvl"), "corrupt": bool(item.get("corrupted")),
            # pseudo_total_life convention: flat life + Strength/2
            "life": d["life"] + d["str"] // 2, "flat": d["life"], "str": d["str"],
            "fire": d["fire"], "cold": d["cold"], "light": d["light"],
            "price": round(p["amount"] * RATES[p["currency"]], 3),
            "raw": f"{p['amount']} {p['currency']}",
            "seller": (lst.get("account") or {}).get("name", "?"), "mods": mods}


# ------------------------- ceiling probes -------------------------
# ../poe1/knowledge/slots.md ALREADY HAS the measured grid for all six slots.
# Read it first; only re-probe when the league turned over or the request wants
# a slot/stat combination that isn't recorded there.
PROBE_GRID = {           # slot -> [(life_min, total_res_min), ...] at PROBE_CAP
    "helm":  [(140, 80), (160, 70), (170, 40), (180, 20), (200, 20)],
    "glove": [(110, 80), (130, 40), (140, 20), (155, 20)],
    "amu":   [(120, 70), (140, 60), (150, 40), (175, 20)],
    "ring":  [(110, 70), (130, 60), (140, 40), (150, 20)],
    "belt":  [(150, 70), (170, 60), (180, 40), (190, 20), (205, 20)],
}
PROBE_CAP = 5.0          # chaos; ~BUDGET/len(SLOT_ORDER)


def cmd_probe():
    """Count-only probes. >200 hits = thresholds too soft, ~0 = too hard.
    Reading `total` needs no fetch, so this is cheap on the rate limit."""
    print(f"probe cap={PROBE_CAP:g}c  (counts are listings at or under that price)\n")
    for slot, grid in PROBE_GRID.items():
        for life, res in grid:
            http_search(f"probe_{slot}_L{life}_R{res}",
                        q(CAT[slot], [SF(TOT_LIFE, life), SF(TOT_RES, res)],
                          price_max=PROBE_CAP))
        # element-specific: pseudo_total_elemental_resistance is ELEMENT-BLIND,
        # so a lopsided requirement (F129 vs C62) needs its own pool.
        http_search(f"probe_{slot}_fire",
                    q(CAT[slot], [SF(TOT_LIFE, PROBE_GRID[slot][0][0]), SF(TOT_FIRE, 40)],
                      price_max=PROBE_CAP))


# ------------------------- pools -------------------------
# Worked example: the 2026-07-28 six-slot task. Thresholds came from the probe
# grid above (counts in ../poe1/knowledge/slots.md), NEVER guessed. Each slot
# gets four shapes so the optimizer can trade life against resistance freely:
#   _maxlife  push life, resistance barely filtered
#   _bal      balanced
#   _res      push resistance
#   _fire     element-specific (the lopsided constraint)
# Redo the probes and retune these for a different budget or requirement.
POOLS = {
    "helm_maxlife": ("helm", [SF(TOT_LIFE, 165), SF(TOT_RES, 30)]),
    "helm_bal":     ("helm", [SF(TOT_LIFE, 145), SF(TOT_RES, 70)]),
    "helm_res":     ("helm", [SF(TOT_LIFE, 125), SF(TOT_RES, 95)]),
    "helm_fire":    ("helm", [SF(TOT_LIFE, 140), SF(TOT_FIRE, 40)]),
    "helm_top":     ("helm", [SF(TOT_LIFE, 185), SF(TOT_RES, 30)]),
    "helm_dual":    ("helm", [SF(TOT_LIFE, 178), SF(TOT_RES, 65)]),

    "glove_maxlife": ("glove", [SF(TOT_LIFE, 130), SF(TOT_RES, 30)]),
    "glove_bal":     ("glove", [SF(TOT_LIFE, 108), SF(TOT_RES, 72)]),
    "glove_res":     ("glove", [SF(TOT_LIFE, 90), SF(TOT_RES, 92)]),
    "glove_fire":    ("glove", [SF(TOT_LIFE, 100), SF(TOT_FIRE, 40)]),
    "glove_top":     ("glove", [SF(TOT_LIFE, 145), SF(TOT_RES, 30)]),

    "amu_maxlife": ("amu", [SF(TOT_LIFE, 145), SF(TOT_RES, 35)]),
    "amu_bal":     ("amu", [SF(TOT_LIFE, 120), SF(TOT_RES, 70)]),
    "amu_res":     ("amu", [SF(TOT_LIFE, 105), SF(TOT_RES, 88)]),
    "amu_fire":    ("amu", [SF(TOT_LIFE, 120), SF(TOT_FIRE, 40)]),
    "amu_top":     ("amu", [SF(TOT_LIFE, 158), SF(TOT_RES, 30)]),

    "ring_maxlife": ("ring", [SF(TOT_LIFE, 132), SF(TOT_RES, 35)]),
    "ring_bal":     ("ring", [SF(TOT_LIFE, 112), SF(TOT_RES, 72)]),
    "ring_res":     ("ring", [SF(TOT_LIFE, 98), SF(TOT_RES, 95)]),
    "ring_fire":    ("ring", [SF(TOT_LIFE, 110), SF(TOT_FIRE, 40)]),
    "ring_fire2":   ("ring", [SF(TOT_LIFE, 120), SF(TOT_FIRE, 35)]),
    "ring_top":     ("ring", [SF(TOT_LIFE, 145), SF(TOT_RES, 30)]),
    "ring_dual":    ("ring", [SF(TOT_LIFE, 133), SF(TOT_RES, 60)]),

    "belt_maxlife": ("belt", [SF(TOT_LIFE, 178), SF(TOT_RES, 35)]),
    "belt_bal":     ("belt", [SF(TOT_LIFE, 152), SF(TOT_RES, 70)]),
    "belt_res":     ("belt", [SF(TOT_LIFE, 135), SF(TOT_RES, 88)]),
    "belt_fire":    ("belt", [SF(TOT_LIFE, 150), SF(TOT_FIRE, 40)]),
    "belt_top":     ("belt", [SF(TOT_LIFE, 190), SF(TOT_RES, 30)]),
    "belt_dual":    ("belt", [SF(TOT_LIFE, 183), SF(TOT_RES, 65)]),
}


def cmd_pools(force=False):
    for name, (slot, stats) in POOLS.items():
        run_pool(name, q(CAT[slot], stats), force=force)


# ------------------------- optimizer -------------------------
# The joint problem: pick 6 listings (one per SLOT_ORDER entry, rings distinct)
# maximising total life s.t. per-element resistance minimums and a total price
# cap. Brute force is ~2.8e12 combinations on real pool sizes -- not an option.
#
# Three ideas make it EXACT and fast:
#  1. CLAMP each partial aggregate's resistance at the requirement. Surplus fire
#     beyond NEED[0] is worth exactly nothing, so (F,C,L) collapses onto a finite
#     lattice instead of an unbounded sum. This is what makes the rest possible.
#  2. Per lattice cell keep only the price/life PARETO FRONTIER. Lossless: a
#     query only ever asks "best life at res >= X, price <= Y", so a costlier
#     entry with no more life in the same cell can never win.
#  3. Join the two halves through a 3-D SUFFIX-MAX table, built incrementally in
#     price order. Each armour aggregate then costs ONE array lookup.
#
# Measured against a 6-nested-loop brute force on random subsets (`selftest`):
# identical at every budget tier. The POE2 sibling's prune_groups() bucket cap
# UNDERSTATED this task by 19 life (it truncated 6% of one half and 18% of the
# other), which is why this replaces it rather than reusing it.
_SOLD = "sold.json"          # item ids confirmed sold, shared by every re-solve


def tkey(b):
    """Canonical tier key: 15 and 15.0 and "15.0" must all mean "15", otherwise
    result.json keys depend on how the tier was passed in and verify/report
    KeyError on a tier that solve definitely wrote."""
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
    """parsed_*.json -> {slot: [candidate, ...]}, deduped by item id (cheapest
    wins when the same listing shows up in several pools)."""
    excl = sold_ids()
    by_slot = {s: {} for s in CAT}
    for fn in sorted(glob.glob(os.path.join(WORKDIR, "parsed_*.json"))):
        d = json.load(open(fn))
        name = d.get("name", "")
        slot = POOLS.get(name, (None,))[0]
        if slot is None:                       # tolerate hand-added pools
            slot = next((s for s in CAT if name.startswith(s + "_")), None)
        if slot is None:
            continue
        for r in d.get("rows", []):
            if r["id"] in excl or r["price"] > BUDGET:
                continue
            r = dict(r, pool=name, slot=slot)
            old = by_slot[slot].get(r["id"])
            if old is None or r["price"] < old["price"]:
                by_slot[slot][r["id"]] = r
    return {k: list(v.values()) for k, v in by_slot.items()}


AXES = ("life", "fire", "cold", "light")


def pareto(cands):
    """Drop candidates another beats on price AND all four axes."""
    out = []
    for c in sorted(cands, key=lambda c: (c["price"], -c["life"])):
        if not any(all(k[a] >= c[a] for a in AXES) and k["price"] <= c["price"] for k in out):
            out.append(c)
    return out


def thin(cands, k):
    """Keep the frontier EXTREMES, not the top-k of one ranking.

    Top-k by life alone would discard the high-resistance items the constraints
    need; top-k by resistance alone caps achievable life. So union the leaders on
    every axis the optimizer trades off. Measured on the reference task
    (~120 candidates/slot, see ../common/tricks.md):
        k=90 -> 7s, max-budget tier EXACT ; k=75 -> 6s, EXACT ; k=60 -> 3s, EXACT
        k=45 -> 2s, -3 life ; k=35 -> 2s, -17 life        (exact run was ~4 min)
    Mid tiers lose 5-8 life well before the headline tier does -- matching the
    general "headline tiers converge earlier" note in ../common/tricks.md.
    """
    if len(cands) <= k:
        return cands
    n = max(4, k // 5)
    keep, seen = [], set()
    for key in (lambda c: -c["life"],
                lambda c: -c["fire"],
                lambda c: -c["cold"],
                lambda c: -c["light"],
                lambda c: -(c["fire"] + c["cold"] + c["light"]),
                lambda c: -c["life"] / max(c["price"], 0.5),
                lambda c: (c["price"], -c["life"])):
        for c in sorted(cands, key=key)[:n]:
            if c["id"] not in seen:
                seen.add(c["id"])
                keep.append(c)
    return keep


def prep(pools):
    p = {k: pareto(v) for k, v in pools.items()}
    if FAST:
        p = {k: thin(v, FAST) for k, v in p.items()}
    return p


def frontier(groups, need):
    """Per clamped (F,C,L), keep only the price/life Pareto frontier. Lossless."""
    by_key = {}
    for g in groups:
        by_key.setdefault((g[2], g[3], g[4]), []).append(g)
    out = []
    for lst in by_key.values():
        lst.sort(key=lambda g: (g[0], -g[1]))
        best = -1
        for g in lst:
            if g[1] > best:
                best = g[1]
                out.append(g)
    return out


def combine(groups, cands, need):
    """groups x cands -> clamped aggregates, deduped then Pareto-pruned.
    Group tuple = (price, life, F, C, L, items)."""
    best = {}
    for gp, gl, gf, gc, gli, gitems in groups:
        for c in cands:
            p = round(gp + c["price"], 3)
            if p > BUDGET:
                continue
            key = (min(gf + c["fire"], need[0]), min(gc + c["cold"], need[1]),
                   min(gli + c["light"], need[2]), round(p * 20))
            life = gl + c["life"]
            cur = best.get(key)
            if cur is None or life > cur[1]:
                best[key] = (p, life, key[0], key[1], key[2], gitems + (c,))
    return frontier(list(best.values()), need)


def ring_pairs(rings, need):
    """Unordered distinct pairs -> clamped aggregates."""
    out = {}
    for r1, r2 in itertools.combinations(rings, 2):
        pr = round(r1["price"] + r2["price"], 3)
        if pr > BUDGET:
            continue
        key = (min(r1["fire"] + r2["fire"], need[0]), min(r1["cold"] + r2["cold"], need[1]),
               min(r1["light"] + r2["light"], need[2]), round(pr * 20))
        life = r1["life"] + r2["life"]
        if key not in out or life > out[key][1]:
            out[key] = (pr, life, key[0], key[1], key[2], (r1, r2))
    return frontier(list(out.values()), need)


def build_halves(p, need):
    """(armour = helm x glove x amu, jewellery = ring pair x belt)."""
    zero = [(0.0, 0, 0, 0, 0, ())]
    A = combine(combine(combine(zero, p["helm"], need), p["glove"], need), p["amu"], need)
    J = combine(ring_pairs(p["ring"], need), p["belt"], need)
    return A, J


def solve(A, J, budget, need):
    """max total life over A x J meeting `need` within `budget`. Exact."""
    if not A or not J:
        return None
    jp = np.array([g[0] for g in J])
    jl = np.array([g[1] for g in J], dtype=np.int32)
    jf = np.array([g[2] for g in J]); jc = np.array([g[3] for g in J])
    jli = np.array([g[4] for g in J])
    order = np.argsort(jp, kind="stable")
    jp, jl, jf, jc, jli = jp[order], jl[order], jf[order], jc[order], jli[order]

    ap = np.array([g[0] for g in A])
    al = np.array([g[1] for g in A], dtype=np.int32)
    af = np.array([g[2] for g in A]); ac = np.array([g[3] for g in A])
    ali = np.array([g[4] for g in A])
    idxA = np.nonzero(ap <= budget)[0]
    if idxA.size == 0:
        return None
    # Bin the remaining budget DOWN to 0.05c so a bin's jewellery price ceiling
    # never exceeds the true remaining budget (conservative, never overspends).
    bins = np.floor((budget - ap[idxA]) * 20).astype(np.int64)

    T = np.full((need[0] + 1, need[1] + 1, need[2] + 1), -1, dtype=np.int32)
    best, nxt = None, 0
    for b in np.unique(bins):
        limit = b / 20.0
        while nxt < jp.size and jp[nxt] <= limit + 1e-9:
            if jl[nxt] > T[jf[nxt], jc[nxt], jli[nxt]]:
                T[jf[nxt], jc[nxt], jli[nxt]] = jl[nxt]
            nxt += 1
        if nxt == 0:
            continue
        S = T.copy()                                  # suffix max over all 3 axes
        np.maximum.accumulate(S[::-1, :, :], axis=0, out=S[::-1, :, :])
        np.maximum.accumulate(S[:, ::-1, :], axis=1, out=S[:, ::-1, :])
        np.maximum.accumulate(S[:, :, ::-1], axis=2, out=S[:, :, ::-1])
        sel = idxA[bins == b]
        got = S[np.maximum(need[0] - af[sel], 0),
                np.maximum(need[1] - ac[sel], 0),
                np.maximum(need[2] - ali[sel], 0)]
        tot = al[sel] + got
        tot[got < 0] = -1
        k = int(np.argmax(tot))
        if tot[k] >= 0 and (best is None or tot[k] > best[0]):
            best = (int(tot[k]), int(sel[k]), float(limit))
    if best is None:
        return None
    _, ai, limit = best
    a = A[ai]
    lo = (max(need[0] - a[2], 0), max(need[1] - a[3], 0), max(need[2] - a[4], 0))
    cand = [g for g in J if g[0] <= limit + 1e-9
            and g[2] >= lo[0] and g[3] >= lo[1] and g[4] >= lo[2]]
    if not cand:
        return None
    return a, max(cand, key=lambda g: (g[1], -g[0]))


def summarize(a, j):
    items = list(a[5]) + list(j[5])
    tot = {k: sum(i[k] for i in items) for k in AXES}
    return {"life": tot["life"], "price": round(sum(i["price"] for i in items), 3),
            "res": tot, "items": items}


def cmd_solve(margin=None, tiers=None, quiet=False):
    margin = MARGIN if margin is None else margin
    need = tuple(n + margin for n in NEED)
    p = prep(load())
    if not quiet:
        print(f"need F{need[0]} C{need[1]} L{need[2]} (buffer +{margin})"
              f"{'  FAST=' + str(FAST) if FAST else '  EXACT'}")
        print("candidates:", {k: len(v) for k, v in p.items()}, flush=True)
    A, J = build_halves(p, need)
    if not quiet:
        print(f"groups A={len(A)} J={len(J)}", flush=True)
    out = {}
    for b in (tiers or TIERS):
        r = solve(A, J, float(b), need)
        if not r:
            print(f"[<= {b:g}c] no feasible combo", flush=True)
            continue
        s = summarize(*r)
        out[tkey(b)] = {"budget": b, "margin": margin, **s}
        print(f"\n[<= {b:g}c] LIFE={s['life']}  spend={s['price']:.2f}c  "
              f"F{s['res']['fire']} C{s['res']['cold']} L{s['res']['light']}", flush=True)
        if not quiet:
            for i in s["items"]:
                print(f"   {i['slot']:6s} {i['raw']:>13s} L{i['life']:>4} "
                      f"F{i['fire']:>3} C{i['cold']:>3} L{i['light']:>3}  "
                      f"{i['name'][:34]:34s} @{i['seller']} [{i['pool']}]", flush=True)
    json.dump(out, open(os.path.join(WORKDIR, "result.json"), "w"), indent=1)
    return out


# ------------------------- selftest -------------------------
def cmd_selftest(k=7, seed=7):
    """Cross-check solve() against a literal 6-nested-loop brute force on a
    random subset, and assert the returned combo is actually legal.
    RUN THIS after touching the optimizer -- a silent off-by-one in the clamp or
    the suffix-max direction produces plausible-but-wrong answers."""
    import random
    random.seed(seed)
    need = tuple(n + MARGIN for n in NEED)
    p = {kk: pareto(v) for kk, v in load().items()}
    sub = {kk: random.sample(v, min(k, len(v))) for kk, v in p.items()}
    if any(len(v) < 2 for v in sub.values()):
        sys.exit("not enough candidates cached -- run `pools` first")
    A, J = build_halves(sub, need)
    fails = 0
    for budget in (8, 12, 16, 20, 25, 30):
        bf = None
        for h, g, a in itertools.product(sub["helm"], sub["glove"], sub["amu"]):
            for r1, r2 in itertools.combinations(sub["ring"], 2):
                for b in sub["belt"]:
                    items = (h, g, a, r1, r2, b)
                    if round(sum(i["price"] for i in items), 3) > budget + 1e-9:
                        continue
                    if any(sum(i[key] for i in items) < nd
                           for key, nd in zip(("fire", "cold", "light"), need)):
                        continue
                    life = sum(i["life"] for i in items)
                    if bf is None or life > bf:
                        bf = life
        r = solve(A, J, float(budget), need)
        got = None
        if r:
            s = summarize(*r)
            got = s["life"]
            assert s["price"] <= budget + 1e-9, f"OVER BUDGET {s['price']} > {budget}"
            assert len({i["id"] for i in s["items"]}) == 6, "duplicate listing used"
            for key, nd in zip(("fire", "cold", "light"), need):
                assert s["res"][key] >= nd, f"{key} short: {s['res'][key]} < {nd}"
        ok = got == bf
        fails += not ok
        print(f"budget {budget:>3}c  bruteforce={bf}  solve={got}  "
              f"{'OK' if ok else '*** MISMATCH ***'}")
    print("\nRESULT:", "all match" if not fails else f"{fails} MISMATCHES")
    return 1 if fails else 0


# ------------------------- verification & buy links -------------------------
# ../common/delivery.md wants a seller-account-filtered link per item. The
# account name MUST carry its #1234 discriminator -- without it the search
# returns 0 results SILENTLY rather than erroring.
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
    """Seller + slot + life-floor. Narrow enough to usually return exactly 1."""
    return {"query": {"status": {"option": "securable"},
                      "stats": [{"type": "and", "filters": [SF(TOT_LIFE, it["life"])]}],
                      "filters": {
                          "type_filters": {"filters": {"category": {"option": CAT[it["slot"]]},
                                                       "rarity": {"option": RARITY}}},
                          "trade_filters": {"filters": {"account": {"input": it["seller"]}}}}},
            "sort": {"price": "asc"}}


def verify_one(it):
    body = seller_query(it)
    mode = transport()
    if mode == "http":
        s = req(SEARCH_URL.format(league=LEAGUE), json.dumps(body).encode("utf-8"))
        time.sleep(1.5)
        found, qid = None, s["id"]
        hashes = (s.get("result") or [])[:FETCH_CAP]
        if hashes:
            j = req(FETCH_URL.format(ids=",".join(hashes), qid=qid))
            for x in (j.get("result") or []):
                if x and x.get("item", {}).get("id") == it["id"]:
                    p = (x.get("listing") or {}).get("price") or {}
                    found = {"price": f"{p.get('amount')} {p.get('currency')}",
                             "gone": bool(x.get("gone"))}
            time.sleep(1.5)
        d = {"qid": qid, "total": s.get("total"), "found": found}
    else:
        js = (_VERIFY_JS.replace("__BODY__", json.dumps(body))
                        .replace("__WANT__", json.dumps(it["id"]))
                        .replace("__LEAGUE_ENC__", LEAGUE.replace(" ", "%20")))
        d = _playwright(js, "verify")
    return {**it, "url": RESULT_URL.format(league=LEAGUE.replace(" ", "%20"),
                                           qid=d.get("qid", "")),
            "seller_total": d.get("total"), "live": bool(d.get("found")),
            "live_price": (d.get("found") or {}).get("price")}


def cmd_verify(tier=None):
    res = json.load(open(os.path.join(WORKDIR, "result.json")))
    tier = tkey(tier) if tier is not None else max(res, key=lambda k: float(k))
    out = [verify_one(it) for it in res[tier]["items"]]
    for i in out:
        print(f"{i['slot']:6s} {i['name'][:32]:32s} @{i['seller']:20s} "
              f"total={i['seller_total']} live={i['live']} {i['live_price'] or ''}")
    payload = {"verified_at": time.strftime("%Y-%m-%d %H:%M"), "tier": tier,
               "life": res[tier]["life"], "price": res[tier]["price"],
               "res": res[tier]["res"], "items": out}
    json.dump(payload, open(os.path.join(WORKDIR, f"verified_{tier}.json"), "w"), indent=1)
    print(f"\nall_live={all(i['live'] for i in out)} -> verified_{tier}.json")
    return payload


def cmd_converge(tiers=None, rounds=6):
    """solve -> verify -> drop sold -> repeat, until every target tier is fully
    live. This is the command to run when the user says "it sold" -- pair it with
    POE_FAST so each round is seconds, because the market moves in minutes."""
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
                print(f"     SOLD {i['slot']} {i['name'][:32]} {i['raw']} @{i['seller']}")
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
    """Markdown deliverable per ../common/delivery.md, written to the project
    root (chat output scrolls away; a timestamped file survives)."""
    tiers = [tkey(t) for t in (tiers or [TIERS[-1]])]
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

    L = [f"# POE1 配裝查詢結果（{LEAGUE}）", "",
         f"- **產生時間**：{time.strftime('%Y-%m-%d %H:%M')}",
         f"- **需求**：{'／'.join(ZH[s] + ('×%d' % SLOT_ORDER.count(s) if SLOT_ORDER.count(s) > 1 else '') for s in dict.fromkeys(SLOT_ORDER))}"
         f" 共 {len(SLOT_ORDER)} 件；"
         f"火 {NEED[0]}% / 冰 {NEED[1]}% / 雷 {NEED[2]}%，並在此前提下把 maximum Life 拉到最高",
         f"- **預算**：{BUDGET:g} chaos｜**緩衝**：三抗各 +{MARGIN}",
         f"- **限制**：{RARITY} 裝；裝備需求等級 ≤ {REQ_LVL_MAX}；Instant Buyout（`securable`）",
         f"- **匯率**：1 divine = {RATES['divine']:.2f} chaos（會漂，跨日務必重抓）",
         "- **Life 口徑**：`+# to maximum Life` + 力量÷2"
         "（力量含 `+# to Strength`／`Strength and X`／`all Attributes`，各只計一次）", ""]

    for v in vs:
        L += [f"## 方案：{v['price']:.2f}c，Life {v['life']}", "",
              f"- **總價格**：**{v['price']:.2f} chaos**"
              f"（約 {v['price']/RATES['divine']:.3f} divine）；總 maximum Life = **{v['life']}**",
              "- **需求檢核**：" + "｜".join(
                  f"{n} **{v['res'][k]}** / 需求 {nd}（+{v['res'][k]-nd}）"
                  for k, n, nd in zip(("fire", "cold", "light"), ("火抗", "冰抗", "雷抗"), NEED)),
              f"- **驗證在架**：{v['verified_at']} 逐件重查賣家掛單並比對物品 id"
              f"（{'全部 live' if all(i['live'] for i in v['items']) else '⚠ 部分已售出'}）", "",
              "| 部位 | 名稱 | 關鍵屬性 | 價格 | 購買連結 | 備註 |",
              "|---|---|---|---|---|---|"]
        seen_ring = 0
        for it in v["items"]:
            if it["slot"] == "ring":
                seen_ring += 1
                label = f"戒指{seen_ring}"
            else:
                label = ZH[it["slot"]]
            attr = (f"Life **{it['life']}**（flat {it['flat']}"
                    + (f" + 力量 {it['str']}/2" if it["str"] else "") + "）"
                    + f"<br>火 {it['fire']} / 冰 {it['cold']} / 雷 {it['light']}")
            note = []
            if it["id"] in shared:
                note.append("**多套共用同一件**")
            if it.get("corrupt"):
                note.append("已腐化")
            if (it.get("seller_total") or 1) > 1:
                note.append(f"該賣家有 {it['seller_total']} 件符合，認價格 {it['raw']}")
            if not it["live"]:
                note.append("**⚠ 已售出，請改用替代連結**")
            alt = pool_qid.get(it.get("pool"))
            if alt:
                note.append(f"[同規格替代]({RESULT_URL.format(league=LEAGUE, qid=alt)})")
            L.append(f"| {label} | {it['name']} | {attr} | {it['raw']}"
                     f"（{it['price']:.2f}c） | [打開]({it['url']}) | "
                     f"{'；'.join(note) or '—'} |")
        L.append("")

    L += ["## 通用注意事項", "",
          "- **這個價位是分鐘級售出**：交付前務必 `converge` 到全部在架；拖越久越可能失效。"
          "連結失效就用備註的「同規格替代」挑同級品，抗性差額從其他部位補。",
          "- **購買連結是「賣家＋部位＋血量下限」的過濾搜尋**（帳號名含 `#1234`，"
          "缺了會靜靜回 0 筆）。多筆時請認備註標的價格。",
          f"- **三抗刻意留 +{MARGIN} 緩衝**：不留緩衝只多幾點血，卻讓任何一件售出／"
          "詞綴判讀誤差都直接破防。",
          "- **力量換血已計入**；實際面板還會再吃天賦的 %increased Life。",
          "- 掛單皆為 Instant Buyout，可直接 whisper；本工具不會替你送出交易訊息。", ""]

    root = out_dir or os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                   "..", "..", "..", ".."))
    fn = os.path.join(root, f"search_results_{time.strftime('%Y%m%d%H%M')}.md")
    open(fn, "w", encoding="utf-8").write("\n".join(L))
    print("wrote", fn)
    return fn


# ------------------------- main -------------------------
def main():
    cmds = {"probe", "pools", "solve", "verify", "converge", "report", "selftest"}
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    cmd = argv[0] if argv else "solve"
    if cmd not in cmds:
        sys.exit(__doc__.split("Usage:")[1].split("Requires")[0])
    os.makedirs(WORKDIR, exist_ok=True)
    rest = argv[1:]
    if cmd == "probe":
        cmd_probe()
    elif cmd == "pools":
        cmd_pools(force="--force" in sys.argv)
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


if __name__ == "__main__":   # never put searches at module level (import re-runs them)
    main()
