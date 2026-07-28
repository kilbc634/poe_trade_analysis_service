# -*- coding: utf-8 -*-
"""Post-optimizer delivery helper: verify winning listings are still live and
build seller-account-filtered search links (../common/delivery.md).

!! REALM: POE2 ONLY as written (CAT[] category options and the stat ids it pulls
!! from gear_combo_optimizer_poe2 are POE2's). The delivery format itself is shared.

Usage: python verify_links.py [tier ...]   (default: the two largest tiers)
Reads gear_pools/result.json + the s_<pool>.json search caches (for query ids),
single-hash fetches each unique item (live check + current price), then POSTs a
narrowed seller-filtered search per item. Writes gear_pools/verify_links.json.
Rate pace: reuses gear_combo_optimizer_poe2.req (header-adaptive + 429 backstop).
NOTE: the POE1 side does NOT need this file -- gear_combo_optimizer_poe1.py has
verification and report generation built in as subcommands.
"""
import json, os, sys, time, glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gear_combo_optimizer_poe2 as g

CAT = {"chest": "armour.chest", "boots": "armour.boots", "helm": "armour.helmet",
       "ring": "accessory.ring", "belt": "accessory.belt"}

def pool_qid(pool):
    return json.load(open(f"{g.WORKDIR}/s_{pool}.json"))["id"]

def seller_query(c):
    stats, filters = [], {
        "type_filters": {"filters": {"category": {"option": CAT[c["slot"]]}}},
        "trade_filters": {"filters": {"account": {"input": c["seller"]}}}}
    if c["slot"] in ("chest", "boots", "helm"):
        filters["equipment_filters"] = {"filters": {"es": {"min": max(c["es"] - 5, 0)}}}
        if c["spirit"]:
            sid = g.SPIRIT_CHEST if c["slot"] == "chest" else g.SPIRIT_BOOTS
            stats.append(g.SF(sid, c["spirit"]))
    else:  # ring/belt: narrow by flat mana (+res for belts)
        if c["mana"]:
            stats.append(g.SF(g.TOT_MANA, max(c["mana"] - 5, 0)))
        tot = c["fire"] + c["cold"] + c["light"]
        if c["slot"] == "belt" and tot:
            stats.append(g.SF(g.TOT_RES, tot - 5))
    return {"query": {"status": {"option": "any"},
                      "stats": [{"type": "and", "filters": stats}],
                      "filters": filters},
            "sort": {"price": "asc"}}

def main():
    r = json.load(open(f"{g.WORKDIR}/result.json"))
    tiers = sys.argv[1:] or sorted(r["tiers"], key=int, reverse=True)[:2]
    items = {}
    for t in tiers:
        if r["tiers"].get(t):
            for c in r["tiers"][t][2]:
                items.setdefault(c["id"], c)
    out = {}
    for iid, c in items.items():
        j = g.req(f"https://www.pathofexile.com/api/trade2/fetch/{iid}"
                  f"?query={pool_qid(c['pool'])}&realm=poe2")
        res = (j.get("result") or [None])[0]
        live = bool(res) and not res.get("gone")
        price = ""
        if live:
            p = res["listing"].get("price") or {}
            price = f"{p.get('amount')} {p.get('currency')}"
        time.sleep(1.5)
        s = g.req(f"https://www.pathofexile.com/api/trade2/search/poe2/{g.LEAGUE}",
                  json.dumps(seller_query(c)).encode("utf-8"))
        out[iid] = {"slot": c["slot"], "name": f"{c['name']} {c['base']}".strip(),
                    "live": live, "cur_price": price, "listed_price": c["cur"],
                    "link_qid": s.get("id"), "link_total": s.get("total"),
                    "err": s.get("error")}
        print(json.dumps(out[iid], ensure_ascii=False), flush=True)
        time.sleep(2)
    json.dump(out, open(f"{g.WORKDIR}/verify_links.json", "w"), indent=1)

if __name__ == "__main__":
    main()
