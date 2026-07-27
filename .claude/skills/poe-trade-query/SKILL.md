---
name: poe-trade-query
description: Build and run Path of Exile trade searches (POE1 /trade and POE2 /trade2) — the query JSON for the search API, how the filters work (field ids, option values, stat filters), and how to drive the search UI. Use whenever the user asks to find/search/price-check items with specific conditions on the POE trade site, so you don't have to rediscover the site's usage. This file is a ROUTER: it decides which game you are on, then sends you to that game's own knowledge tree (poe1/ or poe2/) plus the shared transport layer (common/). Ships a grow-over-time knowledge base — grep it on demand per request, and append new facts the user teaches. Companion to open-poe-trade (which gets the site open & logged in).
---

# POE Trade — router

POE1 and POE2 are **two different games sharing one website**. The transport layer (Cloudflare, auth, rate limits) is common; **everything about the games is not**. This file routes you to the right tree and then gets out of the way.

## Step 0 — Determine the realm. Do this FIRST, before reading anything else.

1. Read `REALM` from `setting.py` (`poe1` or `poe2`) — this is the default answer.
2. If the user explicitly names a game, the user wins. But if that contradicts `REALM`, **say so and ask whether to switch `setting.py`** before doing bulk work — `LEAGUE` in `setting.py` is a single shared field, so a realm the user names by hand is very likely paired with the *other* game's league name (POE1 例：`Allflame`；POE2 例：`Runes of Aldur`). A wrong league usually returns **empty results, not an error.** Read the league name from `setting.py` too; the examples here go stale every league.
3. Never infer the realm from vocabulary in the request. "他提到 Spirit 所以應該是 POE2" is exactly the reasoning that produces silently-wrong answers.

## The isolation rule (no exceptions)

**The current realm's directory is the ONLY source of truth for anything game-related** — stat ids, category options, filter field names, item names, mechanics, valuation, prices, mod-text parsing.

- The other realm's directory **does not exist** for this task. Don't read it, don't grep it, don't cite it, don't diff against it.
- **No cross-game analogy, ever.** Not for a stat id, not for a currency, not for a mechanic, not even as a guess prefaced with "probably". If the current realm's tree doesn't say it, the answer is "我不知道，需要實測" — then go measure it and write it down.
- **Never reuse a stat id from memory.** Both games use the format `<group>.stat_<hash>`. A hash from the wrong game may be *silently valid* in this one and mean something else — the API won't error, it will just return the wrong items. Every id must be freshly grepped from **this realm's** `references/stats.tsv`.
  - Measured 2026-07-28 by diffing the two `references/stats.tsv`: in the `explicit` group alone **528 hashes exist in both games — 274 of them mean something different**, 254 are identical. Examples: `explicit.stat_587431675` = POE1「增加全域暴擊率」／POE2「增加暴擊率」；`stat_3556824919` = POE1 暴擊傷害加成(multiplier)／POE2 Critical Damage Bonus；`stat_1135194732` = POE1 Enchantment Modifiers／POE2 Instilled Modifiers. So carrying an id across games is roughly a coin flip between "silently wrong results" and "happens to work" — which is exactly why it can't be spot-checked by eye.
- Same-named things are assumed different until this realm's tree proves otherwise. There is deliberately no "collision list" to consult — the list would be nearly every noun in both games, and having one would imply that unlisted terms are safe to carry over. None are.

## Directory map

```
common/     realm-agnostic. Transport (Cloudflare/UA ladder, rate limits, 429 policy),
            realm-agnostic method (ceiling probing, per-slot pooling + local optimization),
            and the deliverable format. Safe to read on any realm.
poe1/       POE1 only — QUERY.md (endpoints + query schema), references/*.tsv, knowledge/
poe2/       POE2 only — QUERY.md (endpoints + query schema), references/*.tsv, knowledge/
scripts/    shared tooling (see each script's header for which realm profile is verified)
```

Every file under `poe1/` and `poe2/` opens with a banner naming its game, game version, and last-verified date. **If you are reading a file whose banner names the other game, you took a wrong turn — stop and back out.** Grep results are self-labelling too: the path contains `poe1/` or `poe2/`.

## Reading protocol

1. Realm decided (Step 0) → read `<realm>/QUERY.md`. That's the query model, endpoints, and filter reference. Read it before building any query.
2. Consult the KB **before** building a query whenever the request involves a specific mod+slot combination, or any "how much is X worth" judgement. Grep `<realm>/knowledge/INDEX.md` and `common/INDEX.md` with keywords from the request — **try both 中文 and English terms** — and read only the files that hit. Don't preload the whole KB.
3. If the KB says a combo is impossible, tell the user instead of running a doomed search.
4. Prereqs for actually running things: **`open-poe-trade`** (gets the site open & logged in, and holds the realm→URL routing table), **`playwright-cli`** (browser mechanics).

## Writing new facts back

When the user teaches something, or you measure something worth keeping, file it by this test:

> **Would this sentence still be true if I switched games?**
> No → `<realm>/knowledge/`. Yes → `common/`.

Anything naming a stat id, filter field, currency, item, mechanic, price, or mod-text format is a **No** — game-specific — even when the surrounding method is shared. When a method is shared but its parameters aren't, split it: the skeleton goes to `common/`, the numbers and field names go to the realm dir.

When unsure, put it in the realm dir. Misfiling into `common/` contaminates the other game; misfiling into a realm dir just means writing it twice.

Then: verify any stat ids against that realm's `references/stats.tsv`, add a bilingual keyword line to the matching `INDEX.md`, and refresh the "最後驗證" date in the file's banner.
