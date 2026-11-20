#!/usr/bin/env python3
"""Price lookup against GGG's public Currency Exchange hourly digest.

Source : https://web.poecdn.com/api/currency-exchange[/<realm>][/<epoch>]
         (official "Public API", no login; one digest per CLOSED hour)
Names  : https://repoe-fork.github.io base_items.json (metadata id -> item name)

Python 3.8+, standard library only. See SKILL.md next to this file.
"""
import argparse
import collections
import html
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

API = "https://web.poecdn.com/api/currency-exchange"
REPOE = "https://repoe-fork.github.io"
WIKI = "https://www.poewiki.net/w/api.php"
UA ="poe-currency-price-skill/1.0 (local price lookup script)"
HOUR = 3600
WIDEN = (1, 6, 24)            # `price` look-back steps when --hours is not given
SPREAD_WARN = 1.25            # flag an item whose markets imply prices this far apart
NAMES_TTL = 7 * 86400
SNAP_KEEP = 72 * HOUR

# base = the currency every price is expressed in; refs = other currencies
# that most markets trade against (priced through their own market vs base).
_POE1 = dict(game="POE1", repoe="", zh=True, base="Chaos Orb", refs=["Divine Orb"])
REALMS = {
    "poe1": dict(_POE1, api=""),
    "xbox": dict(_POE1, api="/xbox"),
    "sony": dict(_POE1, api="/sony"),
    "poe2": dict(game="POE2", api="/poe2", repoe="/poe2", zh=False,
                 base="Exalted Orb", refs=["Divine Orb", "Chaos Orb"]),
}
SHORT = {"Chaos Orb": "c", "Divine Orb": "div", "Exalted Orb": "ex"}

CACHE = os.environ.get("POE_CX_CACHE") or os.path.join(tempfile.gettempdir(), "poe-currency-price")
_last_fetch = [0.0]


def die(msg):
    print("ERROR: " + msg, file=sys.stderr)
    sys.exit(1)


def http_json(url):
    """GET -> (status, parsed json or None). 1 s spacing between network calls."""
    wait = 1.0 - (time.time() - _last_fetch[0])
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            body = r.read()
        status = 200
    except urllib.error.HTTPError as e:
        status, body = e.code, b""
    except urllib.error.URLError as e:
        die("network error for %s: %s" % (url, e.reason))
    finally:
        _last_fetch[0] = time.time()
    if status != 200:
        return status, None
    return status, json.loads(body.decode("utf-8"))


# ---------------------------------------------------------------- snapshots

def snap_path(realm, epoch):
    return os.path.join(CACHE, realm, "%d.json" % epoch)


def snapshot(realm, epoch):
    """One closed hour (epoch = hour START, unix seconds). None if not published."""
    path = snap_path(realm, epoch)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    status, data = http_json("%s%s/%d" % (API, REALMS[realm]["api"], epoch))
    if status == 404:
        return None
    if status != 200:
        die("currency-exchange API returned HTTP %d for epoch %d" % (status, epoch))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def prune(realm):
    d = os.path.join(CACHE, realm)
    if not os.path.isdir(d):
        return
    limit = time.time() - SNAP_KEEP
    for name in os.listdir(d):
        stem = name[:-5]
        if name.endswith(".json") and stem.isdigit() and int(stem) < limit:
            try:
                os.remove(os.path.join(d, name))
            except OSError:
                pass


def latest_epoch(realm):
    e = int(time.time()) // HOUR * HOUR - HOUR
    for _ in range(4):
        if snapshot(realm, e) is not None:
            return e
        e -= HOUR
    die("no published snapshot found in the last 4 hours")


# -------------------------------------------------------------------- names

def repoe_names(cfg):
    status, en = http_json("%s%s/base_items.json" % (REPOE, cfg["repoe"]))
    if status != 200:
        return None
    zh = {}
    if cfg["zh"]:
        status, data = http_json("%s%s/Traditional%%20Chinese/base_items.json" % (REPOE, cfg["repoe"]))
        if status == 200:
            zh = data
    items = {}
    for mid, e in en.items():
        if e.get("name"):
            z = (zh.get(mid) or {}).get("name") or ""
            items[mid] = {"en": e["name"], "zh": z if z != e["name"] else "", "cls": e.get("item_class", "")}
    return items


def wiki_names(ids):
    """POE1 only: poewiki's item table knows new-league currencies before RePoE does."""
    out = {}
    ids = sorted(ids)
    for i in range(0, len(ids), 40):
        where = "items.metadata_id IN (%s)" % ",".join('"%s"' % x.replace('"', "") for x in ids[i:i + 40])
        url = WIKI + "?" + urllib.parse.urlencode({
            "action": "cargoquery", "format": "json", "limit": "500", "tables": "items",
            "fields": "items.name,items.metadata_id,items.class_id", "where": where})
        status, data = http_json(url)
        if status != 200 or not isinstance(data, dict):
            break
        for row in data.get("cargoquery", []):
            t = row.get("title", {})
            if t.get("metadata id") and t.get("name"):
                out[t["metadata id"]] = {"en": html.unescape(t["name"]), "zh": "", "cls": t.get("class id") or ""}
    return out


def load_names(realm, need_ids=()):
    """{metadata id: {"en", "zh", "cls"}}.

    RePoE is the main table (refreshed weekly). It lags behind a new league, so
    ids it does not know are looked up on poewiki (POE1) and retried once a day.
    It also KEEPS items that were removed from the game — a name being in this
    table says nothing about whether the item still exists.
    """
    cfg = REALMS[realm]
    path = os.path.join(CACHE, "names_%s.json" % cfg["game"].lower())
    cache = {"fetched": 0, "items": {}, "extra": {}, "missing": {}}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cache.update(json.load(f))
    now, dirty = time.time(), False
    if now - cache["fetched"] > NAMES_TTL:
        items = repoe_names(cfg)
        if items:
            cache.update(fetched=now, items=items)
            dirty = True
        elif not cache["items"]:
            die("could not download the item name table from RePoE")
    unknown = [i for i in need_ids if i not in cache["items"] and i not in cache["extra"]
               and now - cache["missing"].get(i, 0) > 86400]
    if unknown:
        got = wiki_names(unknown) if cfg["game"] == "POE1" else {}
        cache["extra"].update(got)
        for i in unknown:
            if i not in got:
                cache["missing"][i] = now
        dirty = True
    if dirty:
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    return dict(cache["items"], **cache["extra"])


class Names:
    def __init__(self, table):
        self.t = table

    def en(self, mid):
        e = self.t.get(mid)
        return e["en"] if e else "?" + mid.rsplit("/", 1)[-1]

    def zh(self, mid):
        e = self.t.get(mid)
        return e["zh"] if e else ""

    def cls(self, mid):
        e = self.t.get(mid)
        return e["cls"] if e else ""

    def label(self, mid):
        z = self.zh(mid)
        return "%s（%s）" % (self.en(mid), z) if z else self.en(mid)

    def find(self, name, pool):
        """Exact (case-insensitive, EN or ZH) then unique-substring match within pool."""
        q = name.strip().lower()
        exact = [i for i in pool if q in (self.en(i).lower(), self.zh(i).lower())]
        if exact:
            return exact[0], []
        sub = [i for i in pool if q in self.en(i).lower() or (self.zh(i) and q in self.zh(i).lower())]
        if len(sub) == 1:
            return sub[0], []
        return None, sorted(self.label(i) for i in sub)[:15]


# -------------------------------------------------------------- aggregation

def aggregate(realm, league, epochs):
    """Sum each market over the given hours. Key = (a, b) sorted; ratios are 'b per a'."""
    pairs = {}
    for e in epochs:
        snap = snapshot(realm, e)
        if not snap:
            continue
        for m in snap["markets"]:
            if m["league"] != league:
                continue
            a, b = sorted(m["market_pair"])
            p = pairs.get((a, b))
            if p is None:
                p = pairs[(a, b)] = {"vol": {a: 0, b: 0}, "lo": None, "hi": None,
                                     "stock": {a: 0, b: 0}, "stock_epoch": 0, "hours": 0}
            if e >= p["stock_epoch"]:
                p["stock_epoch"] = e
                p["stock"] = {a: m["highest_stock"][a], b: m["highest_stock"][b]}
            va, vb = m["volume_traded"][a], m["volume_traded"][b]
            if not (va and vb):
                continue
            p["vol"][a] += va
            p["vol"][b] += vb
            p["hours"] += 1
            for key in ("lowest_ratio", "highest_ratio"):
                r = m[key]
                if r[a] and r[b]:
                    x = r[b] / r[a]
                    p["lo"] = x if p["lo"] is None else min(p["lo"], x)
                    p["hi"] = x if p["hi"] is None else max(p["hi"], x)
    return pairs


def price_table(pairs, base, refs):
    """-> (prices {id: value in base}, rows {id: detail}).

    A reference currency is priced by its own market against base. Every other
    item is priced as (value received, in base) / (units traded), summed over
    its markets against already-priced currencies; items with no such market
    get one extra hop through whatever they do trade against.
    """
    legs = collections.defaultdict(list)
    for (a, b), p in pairs.items():
        va, vb = p["vol"][a], p["vol"][b]
        legs[a].append(dict(other=b, vol=va, ovol=vb, lo=p["lo"], hi=p["hi"],
                            stock=p["stock"][a], hours=p["hours"]))
        legs[b].append(dict(other=a, vol=vb, ovol=va,
                            lo=1 / p["hi"] if p["hi"] else None,
                            hi=1 / p["lo"] if p["lo"] else None,
                            stock=p["stock"][b], hours=p["hours"]))

    prices, rows = {base: 1.0}, {}

    def solve(item, known, allowed=None):
        used = [l for l in legs[item] if l["vol"] and l["other"] in known
                and (allowed is None or l["other"] in allowed)]
        if not used:
            return None
        vol = sum(l["vol"] for l in used)
        out = []
        for l in sorted(used, key=lambda l: -l["ovol"] * known[l["other"]]):
            k = known[l["other"]]
            out.append(dict(other=l["other"], volume=l["vol"], other_volume=l["ovol"],
                            price_in_other=l["ovol"] / l["vol"], price=l["ovol"] / l["vol"] * k,
                            low=l["lo"] * k if l["lo"] else None, high=l["hi"] * k if l["hi"] else None,
                            stock=l["stock"], hours=l["hours"]))
        lows = [l["low"] for l in out if l["low"]]
        highs = [l["high"] for l in out if l["high"]]
        each = [l["price"] for l in out]
        return dict(price=sum(l["other_volume"] * known[l["other"]] for l in out) / vol,
                    legs_spread=max(each) / min(each), volume=vol, low=min(lows) if lows else None, high=max(highs) if highs else None,
                    hours=max(l["hours"] for l in out), legs=out)

    for r in refs:
        row = solve(r, prices, allowed={base})
        if row:
            rows[r] = dict(row, indirect=False)
    for r in refs:
        if r in rows:
            prices[r] = rows[r]["price"]
    ref_prices = dict(prices)
    for item in legs:
        if item not in prices:
            row = solve(item, ref_prices)
            if row:
                rows[item] = dict(row, indirect=False)
                prices[item] = row["price"]
    direct = dict(prices)
    for item in legs:
        if item not in prices:
            row = solve(item, direct)
            if row:
                rows[item] = dict(row, indirect=True)
                prices[item] = row["price"]
    return prices, rows


# ------------------------------------------------------------------ output

def num(x):
    if x is None:
        return "-"
    ax = abs(x)
    if ax >= 1000:
        return "{:,.0f}".format(x)
    if ax >= 100:
        return "%.1f" % x
    if ax >= 1:
        return "%.2f" % x
    return "%.4g" % x


def span(start, hours):
    a = datetime.fromtimestamp(start).astimezone()
    b = datetime.fromtimestamp(start + hours * HOUR).astimezone()
    tz = a.strftime("%z")
    return "%s - %s (UTC%s:%s)" % (a.strftime("%Y-%m-%d %H:%M"), b.strftime("%m-%d %H:%M"), tz[:3], tz[3:])


class Ctx:
    """Everything a command needs: realm config, names, latest hour, league."""

    def __init__(self, args):
        self.realm = args.realm
        self.cfg = REALMS[args.realm]
        prune(self.realm)
        self.latest = latest_epoch(self.realm)
        self.snap = snapshot(self.realm, self.latest)
        self.all_ids = {i for m in self.snap["markets"] for i in m["market_pair"]}
        self.names = Names(load_names(self.realm, self.all_ids))
        self._league_ids = None
        self.counts = collections.Counter(m["league"] for m in self.snap["markets"])
        if not self.counts:
            die("the latest snapshot has no markets at all")
        self.auto_league = not getattr(args, "league", None)
        if self.auto_league:
            self.league = self.counts.most_common(1)[0][0]
        else:
            hit = [l for l in self.counts if l.lower() == args.league.lower()]
            if not hit:
                die("league %r has no markets in the latest hour. Leagues present: %s"
                    % (args.league, ", ".join(l for l, _ in self.counts.most_common(12))))
            self.league = hit[0]
        by_name = {self.names.en(i): i for i in self.all_ids}
        self.base = by_name.get(self.cfg["base"])
        if not self.base:
            die("base currency %s not found in the snapshot" % self.cfg["base"])
        self.refs = [by_name[r] for r in self.cfg["refs"] if r in by_name]

    @property
    def league_ids(self):
        """Ids that have a market (traded or merely stocked) in this league, latest hour."""
        if self._league_ids is None:
            self._league_ids = {i for m in self.snap["markets"] if m["league"] == self.league
                                for i in m["market_pair"]}
        return self._league_ids

    def resolve(self, name):
        """-> (id or None, note). Only the league's own markets are searched fuzzily;
        the full name table is used for exact names only, because it still lists
        items that no longer exist."""
        mid, cands = self.names.find(name, self.league_ids)
        if mid:
            return mid, ""
        q = name.strip().lower()
        exact = [i for i in self.names.t if q in (self.names.en(i).lower(), self.names.zh(i).lower())]
        if exact:
            return exact[0], ""
        if cands:
            return None, "several markets match, be more specific: " + "; ".join(cands)
        n = sum(1 for i in self.names.t if q in self.names.en(i).lower() or q in self.names.zh(i).lower())
        if n:
            return None, ("%d name(s) in the item table contain this, but NONE has a market in %s this hour — "
                          "removed from the game, not exchange-tradable, or nobody listing it. "
                          "The name table keeps deleted items; do not treat them as existing." % (n, self.league))
        return None, "nothing with this name in the markets or in the item table."

    def epochs(self, hours):
        return [self.latest - i * HOUR for i in range(hours)]

    def table(self, hours):
        self.pairs = aggregate(self.realm, self.league, self.epochs(hours))
        return price_table(self.pairs, self.base, self.refs)

    def cross_rates(self):
        """Direct markets between two non-base reference currencies (e.g. POE2 div|chaos)."""
        out = []
        for i, a in enumerate(self.refs):
            for b in self.refs[i + 1:]:
                p = self.pairs.get(tuple(sorted((a, b))))
                if p and p["hours"]:
                    out.append("1 %s = %s %s (direct market, vol %s %s)" % (
                        self.unit(a), num(p["vol"][b] / p["vol"][a]), self.unit(b),
                        "{:,}".format(p["vol"][a]), self.unit(a)))
        return out

    def unit(self, mid):
        return SHORT.get(self.names.en(mid), self.names.en(mid))

    def header(self, hours, prices):
        rates = ["1 %s = %s %s" % (self.unit(r), num(prices[r]), self.unit(self.base))
                 for r in self.refs if r in prices] + self.cross_rates()
        return "%s (%s) | league: %s%s | traded %s%s\nrates: %s" % (
            self.cfg["game"], self.realm, self.league,
            " [auto: busiest league, pass --league to change]" if self.auto_league else "",
            span(self.latest - (hours - 1) * HOUR, hours),
            "" if hours == 1 else " [%dh summed]" % hours,
            "; ".join(rates) or "(no reference market traded)")

    def in_refs(self, value, prices):
        """value in base -> 'x c = y div' style string."""
        parts = ["%s %s" % (num(value), self.unit(self.base))]
        parts += ["%s %s" % (num(value / prices[r]), self.unit(r)) for r in self.refs if r in prices]
        return " = ".join(parts)

    def row_json(self, mid, row, prices, hours):
        out = dict(id=mid, name=self.names.en(mid), name_zh=self.names.zh(mid), item_class=self.names.cls(mid),
                   hours=hours, price=row["price"], unit=self.names.en(self.base),
                   volume=row["volume"], low=row["low"], high=row["high"], indirect=row["indirect"],
                   legs_spread=row["legs_spread"],
                   price_in={self.names.en(r): row["price"] / prices[r] for r in self.refs if r in prices},
                   legs=[dict(l, other=self.names.en(l["other"])) for l in row["legs"]])
        return out


def cmd_leagues(args):
    ctx = Ctx(args)
    traded = collections.Counter(m["league"] for m in ctx.snap["markets"] if all(m["volume_traded"].values()))
    out = []
    for league, n in ctx.counts.most_common():
        prices, _ = price_table(aggregate(ctx.realm, league, [ctx.latest]), ctx.base, ctx.refs)
        rates = {ctx.names.en(r): prices[r] for r in ctx.refs if r in prices}
        out.append(dict(league=league, markets=n, traded_markets=traded[league], rates=rates))
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    print("%s (%s) | hour %s" % (ctx.cfg["game"], ctx.realm, span(ctx.latest, 1)))
    for o in out:
        print("  %-40s markets %5d  traded %5d  %s" % (
            o["league"], o["markets"], o["traded_markets"],
            "  ".join("1 %s = %s %s" % (SHORT.get(k, k), num(v), ctx.unit(ctx.base))
                      for k, v in o["rates"].items())))


def cmd_price(args):
    ctx = Ctx(args)
    steps = (args.hours,) if args.hours else WIDEN
    wanted, problems = [], []
    for name in args.items:
        mid, note = ctx.resolve(name)
        if mid and mid not in wanted:
            wanted.append(mid)
        elif not mid:
            problems.append((name, note))
    found, tables = {}, {}
    for hours in steps:
        # no market in the latest hour = nothing even listed; older hours won't help
        todo = [m for m in wanted if m not in found and m != ctx.base and m in ctx.league_ids]
        if not todo:
            break
        prices, rows = tables[hours] = ctx.table(hours)
        for mid in todo:
            if mid in rows:
                found[mid] = (hours, rows[mid], prices)
    head_prices = (tables.get(steps[0]) or ctx.table(steps[0]))[0]
    if args.json:
        print(json.dumps(dict(
            realm=ctx.realm, league=ctx.league, latest_hour_start=ctx.latest, base=ctx.names.en(ctx.base),
            rates={ctx.names.en(r): head_prices[r] for r in ctx.refs if r in head_prices},
            items=[ctx.row_json(m, found[m][1], found[m][2], found[m][0]) for m in wanted if m in found],
            no_trades=[ctx.names.en(m) for m in wanted if m not in found and m != ctx.base],
            unknown=[dict(query=n, note=c) for n, c in problems]), ensure_ascii=False, indent=1))
        return
    print(ctx.header(steps[0], head_prices))
    for mid in wanted:
        print()
        if mid == ctx.base:
            print("%s\n    is the base currency: every price here is quoted in it (1 %s)."
                  % (ctx.names.label(mid), ctx.unit(mid)))
            continue
        if mid not in found:
            if mid in ctx.league_ids:
                print("%s\n    NO TRADES in the last %d hour(s) in %s — no price. It is listed but nothing filled."
                      % (ctx.names.label(mid), steps[-1], ctx.league))
            else:
                print("%s\n    NO MARKET in %s in the latest hour — no price. Removed from the game, not "
                      "exchange-tradable, or nobody listing it. (The name table keeps deleted items.)"
                      % (ctx.names.label(mid), ctx.league))
            continue
        hours, row, prices = found[mid]
        note = "" if hours == steps[0] else "   ** widened to last %dh: no trades in the latest hour **" % hours
        print("%s%s" % (ctx.names.label(mid), note))
        print("    %s   | volume %s over %d traded hour(s) | low-high %s - %s %s%s" % (
            ctx.in_refs(row["price"], prices), "{:,}".format(row["volume"]), row["hours"],
            num(row["low"]), num(row["high"]), ctx.unit(ctx.base),
            "   [INDIRECT: priced through a non-reference market]" if row["indirect"] else ""))
        if row["legs_spread"] > SPREAD_WARN:
            print("    !! markets disagree x%.2f — the blended figure above is unreliable; quote the market "
                  "in the currency you will actually pay with" % row["legs_spread"])
        for l in row["legs"]:
            print("      vs %-16s 1 = %s %-4s (= %s %s)  vol %-10s low-high %s - %s %s  stock(max, latest h) %s" % (
                ctx.names.en(l["other"]), num(l["price_in_other"]), ctx.unit(l["other"]),
                num(l["price"]), ctx.unit(ctx.base),
                "{:,}".format(l["volume"]), num(l["low"]), num(l["high"]), ctx.unit(ctx.base),
                "{:,}".format(l["stock"])))
    for name, note in problems:
        print("\n%r: NOT PRICED — %s" % (name, note))


def cmd_list(args):
    ctx = Ctx(args)
    hours = args.hours or 1
    prices, rows = ctx.table(hours)
    sel = []
    for mid, row in rows.items():
        hay = (ctx.names.en(mid) + " " + ctx.names.zh(mid)).lower()
        if args.match and not all(any(alt.strip() in hay for alt in m.lower().split("|")) for m in args.match):
            continue
        if args.cls and ctx.names.cls(mid).lower() != args.cls.lower():
            continue
        if row["volume"] < args.min_volume:
            continue
        sel.append((mid, row))
    key = {"price": lambda x: -x[1]["price"], "volume": lambda x: -x[1]["volume"],
           "name": lambda x: ctx.names.en(x[0])}[args.sort]
    sel.sort(key=key)
    shown = sel if args.limit == 0 else sel[:args.limit]
    if args.json:
        print(json.dumps(dict(realm=ctx.realm, league=ctx.league, latest_hour_start=ctx.latest, hours=hours,
                              base=ctx.names.en(ctx.base),
                              rates={ctx.names.en(r): prices[r] for r in ctx.refs if r in prices},
                              total=len(sel),
                              items=[ctx.row_json(m, r, prices, hours) for m, r in shown]),
                         ensure_ascii=False, indent=1))
        return
    print(ctx.header(hours, prices))
    if args.classes:
        c = collections.Counter(ctx.names.cls(m) or "(unknown)" for m in rows)
        print("item classes with trades: " + ", ".join("%s %d" % kv for kv in c.most_common()))
    b = ctx.unit(ctx.base)
    others = [r for r in ctx.refs if r in prices]
    print("%10s %s %10s  %-18s %s" % (b, " ".join("%9s" % ctx.unit(r) for r in others), "volume",
                                      "low-high (" + b + ")", "item"))
    for mid, row in shown:
        print("%10s %s %10s  %-18s %s%s%s" % (
            num(row["price"]), " ".join("%9s" % num(row["price"] / prices[r]) for r in others),
            "{:,}".format(row["volume"]), "%s - %s" % (num(row["low"]), num(row["high"])),
            ctx.names.label(mid), "  [indirect]" if row["indirect"] else "",
            "  [markets disagree x%.2f]" % row["legs_spread"] if row["legs_spread"] > SPREAD_WARN else ""))
    print("%d item(s) matched%s" % (len(sel), "" if len(shown) == len(sel) else
                                    ", showing %d (raise --limit, 0 = all)" % len(shown)))


def cmd_pair(args):
    ctx = Ctx(args)
    hours = args.hours or 24
    ids = []
    for name in (args.a, args.b):
        mid, note = ctx.resolve(name)
        if not mid:
            die("%r: %s" % (name, note))
        ids.append(mid)
    a, b = ids
    key = tuple(sorted(ids))
    out = []
    for e in reversed(ctx.epochs(hours)):
        p = aggregate(ctx.realm, ctx.league, [e]).get(key)
        if not p or not p["hours"]:
            out.append(dict(hour_start=e, price=None))
            continue
        lo, hi = p["lo"], p["hi"]
        if key[0] != a:     # stored ratios are key[1] per key[0]; we want b per a
            lo, hi = (1 / hi if hi else None), (1 / lo if lo else None)
        out.append(dict(hour_start=e, price=p["vol"][b] / p["vol"][a], low=lo, high=hi,
                        volume_a=p["vol"][a], volume_b=p["vol"][b],
                        stock_a=p["stock"][a], stock_b=p["stock"][b]))
    if args.json:
        print(json.dumps(dict(realm=ctx.realm, league=ctx.league, a=ctx.names.en(a), b=ctx.names.en(b),
                              price_meaning="b per 1 a", history=out), ensure_ascii=False, indent=1))
        return
    print("%s (%s) | league: %s%s" % (ctx.cfg["game"], ctx.realm, ctx.league,
                                     " [auto: busiest league]" if ctx.auto_league else ""))
    print("1 %s = ? %s, per closed hour (hour START, local time)" % (ctx.names.label(a), ctx.names.label(b)))
    print("%-12s %10s %10s %10s %12s %14s %10s %12s" % ("hour", "price", "low", "high", "vol " + ctx.unit(a),
                                                       "vol " + ctx.unit(b), "stock " + ctx.unit(a),
                                                       "stock " + ctx.unit(b)))
    for r in out:
        t = datetime.fromtimestamp(r["hour_start"]).strftime("%m-%d %H:%M")
        if r["price"] is None:
            print("%-12s %10s" % (t, "no trades"))
            continue
        print("%-12s %10s %10s %10s %12s %14s %10s %12s" % (
            t, num(r["price"]), num(r["low"]), num(r["high"]), "{:,}".format(r["volume_a"]),
            "{:,}".format(r["volume_b"]), "{:,}".format(r["stock_a"]), "{:,}".format(r["stock_b"])))


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--realm", choices=sorted(REALMS), default="poe1",
                        help="poe1 = POE1 PC (default); xbox/sony = POE1 consoles; poe2 = POE2")
    common.add_argument("--league", help="exact league name; default = busiest league of the latest hour")
    common.add_argument("--hours", type=int, help="sum this many closed hours (default 1)")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("leagues", parents=[common], help="leagues present in the latest hour + headline rates")
    p = sub.add_parser("price", parents=[common], help="price named items (EN or ZH name)")
    p.add_argument("items", nargs="+")
    p = sub.add_parser("list", parents=[common], help="price table filtered by name / item class")
    p.add_argument("--match", action="append", help="name substring, EN or ZH; 'a|b' = either; repeat = AND")
    p.add_argument("--class", dest="cls", help="RePoE item_class, e.g. MapFragment, DivinationCard")
    p.add_argument("--classes", action="store_true", help="also print the item classes that traded")
    p.add_argument("--min-volume", type=int, default=0)
    p.add_argument("--sort", choices=["price", "volume", "name"], default="price")
    p.add_argument("--limit", type=int, default=60)
    p = sub.add_parser("pair", parents=[common], help="hourly history of one market (default 24 h)")
    p.add_argument("a")
    p.add_argument("b")
    args = ap.parse_args()
    if args.hours is not None and not 1 <= args.hours <= 168:
        die("--hours must be between 1 and 168")
    {"leagues": cmd_leagues, "price": cmd_price, "list": cmd_list, "pair": cmd_pair}[args.cmd](args)


if __name__ == "__main__":
    main()
