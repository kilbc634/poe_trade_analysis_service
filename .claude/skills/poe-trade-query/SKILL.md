---
name: poe-trade-query
description: Build and run POE2 trade searches — how the search filters work (field ids, option values, stat filters), how to drive the search UI, and the exact query JSON for the search API. Use whenever the user asks to find/search items with specific conditions on the POE trade site, so you don't have to rediscover the site's usage. Ships a grow-over-time knowledge base (knowledge/ dir: mod slot availability, market wisdom, query tricks) — grep it on demand per request, and append new facts the user teaches. Companion to open-poe-trade (which gets the site open & logged in).
---

# POE2 Trade — building search queries

Everything here was captured live from the POE2 trade site (`/trade2`, league from `setting.py`). It covers the three layers you need: **the query model**, **the API way** (preferred), and **the UI way** (when the user wants to see the page).

> Prereq: the site must be open & logged in — use the **`open-poe-trade`** skill first. Browser mechanics come from the **`playwright-cli`** skill.

## Recommended flow: build via API, show via UI

**Price-check tasks need no browser.** The search + fetch APIs work over plain HTTP (curl/httpx) with a full browser UA — anonymously too (response bodies are identical with/without the cookie). **But for any bulk job, send a logged-in `POESESSID` (default: read from `setting.py`).** Anonymous and authenticated traffic sit on *separate* rate-limit pools, and the anonymous pool has an undocumented hidden quota that walls you at ~30 fetches with a ~600s penalty; the authenticated pool doesn't (see knowledge/tricks.md "The header counters are a DECOY"). `gear_combo_optimizer.py` reads `setting.py`'s POESESSID by default and only runs anonymously with `--anon`. Open the browser (via open-poe-trade) only when the user wants to *see* the results page; a logged-in session also matters for actions: whisper/direct-buy (`POST /api/trade2/whisper`), the live-search websocket, and in-page purchase buttons.

The fastest reliable pattern — skip UI form-filling entirely:

1. Build the query JSON (schema below).
2. `POST /api/trade2/search/poe2/{league}` from **inside the page** (in-page `fetch` — already Cloudflare-cleared and carries cookies):
   ```bash
   playwright-cli --raw eval "(async()=>{const body=<QUERY_JSON>;const r=await fetch('/api/trade2/search/poe2/Runes%20of%20Aldur',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const j=await r.json();return JSON.stringify({status:r.status,id:j.id,total:j.total,error:j.error})})()"
   ```
   Returns `{id: <query_id>, result: [item hashes], total}`. On bad input you get `error.message` (e.g. unknown stat id) — fix and retry.

   No browser open? Plain HTTP works just as well — but the User-Agent must be a **full, realistic browser UA string**; a bare `Mozilla/5.0` gets a Cloudflare 403 (verified 2026-07). If `.poe_cookies.json` exists in the project root, also send its cookies (see knowledge/tricks.md — cookie cache):
   ```bash
   curl -s -H "Content-Type: application/json" \
     -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36" \
     -X POST --data @query.json "https://www.pathofexile.com/api/trade2/search/poe2/Runes%20of%20Aldur"
   ```
3. To show the user: `playwright-cli goto "https://www.pathofexile.com/trade2/search/poe2/{league}/{query_id}"` — the UI loads with all filters filled in and results listed.
4. To read results programmatically: `GET /api/trade2/fetch/{hash1,hash2,...}?query={query_id}&realm=poe2` (≤10 hashes per call; see open-poe-trade for listing fields, whisper/hideout tokens, rate-limit headers).

To reverse-engineer an existing search: `GET /api/trade2/search/poe2/{league}/{query_id}?realm=poe2` returns its full `query` JSON (works even for other people's query_ids).

## Query JSON schema (verified working)

```jsonc
{
  "query": {
    "status": { "option": "securable" },      // securable = Instant Buyout (usual default)
    // Item identity — all optional:
    "term": "free text",                       // raw text search ("Custom Search")
    "name": "Temporalis",                      // unique item name (exact)
    "type": "Silk Robe",                       // base type (exact)
    // Stat filters — array of groups:
    "stats": [
      { "type": "and", "filters": [
        { "id": "explicit.stat_3299347043", "value": { "min": 100 }, "disabled": false },
        { "id": "pseudo.pseudo_total_resistance", "value": { "min": 80 } }
      ]}
    ],
    // Non-stat filters — six groups, each { "filters": { <field>: <value> } }:
    "filters": {
      "type_filters":      { "filters": { "category": { "option": "armour.chest" }, "rarity": { "option": "rare" },
                                          "ilvl": { "min": 75 }, "quality": { "min": 20 } } },
      "equipment_filters": { "filters": { "es": { "min": 300 }, "pdps": { "min": 400 } } },
      "req_filters":       { "filters": { "lvl": { "max": 60 } } },
      "map_filters":       { "filters": { "map_tier": { "min": 15 } } },      // "Endgame Filters" in UI
      "misc_filters":      { "filters": { "corrupted": { "option": "false" }, "gem_level": { "min": 19 } } },
      "trade_filters":     { "filters": { "price": { "option": "exalted", "min": 1, "max": 50 },
                                          "indexed": { "option": "1day" } } }
    }
  },
  "sort": { "price": "asc" }
}
```

Value shapes: min/max fields take `{"min": N}` / `{"max": N}` / both; dropdowns take `{"option": "<id>"}`; booleans are the strings `"true"` / `"false"`; omit a field (or pass option `null`-equivalent by omission) for "Any". `status.option`: `securable` (Instant Buyout) | `available` | `online` | `onlineleague` | `any`.

### Stat groups (`stats[].type`)

| type | UI name | meaning |
|---|---|---|
| `and` | And | every filter must match (the default group) |
| `not` | Not | none may match |
| `if` | If | doesn't filter; conditions other groups |
| `count` | Count | `value.min` of `{"type":"count","value":{"min":2},"filters":[...]}` = at least N of the listed stats match (classic "any 2 of these resists") |
| `weight` / `weight2` | Weighted Sum (v2) | each filter gets `value.weight`; sum of weight×statvalue is compared to the group min/max |

Each stat filter: `{"id": "<stat id>", "value": {"min", "max", "weight"?}, "disabled": false}`.

## Stat ids — how to find the right one

Format: `<group>.stat_<hash>` (e.g. `explicit.stat_3299347043`). Groups: `pseudo`, `explicit` (3097 entries — the normal roll pool), `implicit`, `fractured`, `crafted`, `enchant`, `rune`, `desecrated`, `sanctum`, `skill`. The same mod text exists once per group with a **different id** — searching `rune.…` only matches rune-socket mods, etc. For "this mod from any source", prefer **pseudo** when one exists.

**Lookup:** grep `references/stats.tsv` in this skill dir (columns: `group<TAB>id<TAB>text`, `#` = the number placeholder):

```bash
grep -i "maximum life" references/stats.tsv | grep -P "^(pseudo|explicit)"
```

If the TSV seems stale (new league content missing), regenerate it from the live API — the `/api/trade2/data/*` endpoints ARE Cloudflare-protected (plain curl gets an HTML challenge page), so fetch in-page:

```bash
playwright-cli --raw eval "(async()=>{const r=await fetch('/api/trade2/data/stats');return JSON.stringify(await r.json())})()" > stats_raw.json
# note: output is a double-encoded JSON string → json.loads() twice
```

### Pseudo stats (use these for totals across mod sources)

`pseudo.pseudo_total_life`, `pseudo_total_mana`, `pseudo_total_energy_shield`, `pseudo_increased_energy_shield`, `pseudo_total_fire_resistance` / `_cold_` / `_lightning_` / `_chaos_resistance`, `pseudo_total_elemental_resistance` (sum of ele res), `pseudo_total_resistance` (sum incl. chaos), `pseudo_total_all_elemental_resistances` (only "+#% to all"), `pseudo_total_strength` / `_dexterity` / `_intelligence` / `_all_attributes` / `_attributes`, `pseudo_increased_movement_speed`, and mod-count metas: `pseudo_number_of_prefix_mods` / `_suffix_mods` / `_affix_mods` / `_empty_prefix_mods` / `_empty_suffix_mods` / `_fractured_mods` / `_crafted_mods` / `_desecrated_mods` / `_unrevealed_mods` / `_uses_remaining` (tablets).

### Most-used explicit ids (POE2)

| stat text | id |
|---|---|
| # to maximum Life | `explicit.stat_3299347043` |
| # to maximum Mana | `explicit.stat_1050105434` |
| # to maximum Energy Shield | `explicit.stat_3489782002` |
| #% increased maximum Energy Shield | `explicit.stat_2482852589` |
| #% to Fire / Cold / Lightning / Chaos Res | `explicit.stat_3372524247` / `stat_4220027924` / `stat_1671376347` / `stat_2923486259` |
| #% to all Elemental Resistances | `explicit.stat_2901986750` |
| # to Strength / Dexterity / Intelligence | `explicit.stat_4080418644` / `stat_3261801346` / `stat_328541901` |
| # to all Attributes | `explicit.stat_1379411836` (also `stat_2897413282` — two ids exist; test or use pseudo) |
| #% increased Movement Speed | `explicit.stat_2250533757` |
| #% increased Rarity of Items found | `explicit.stat_3917489142` |
| # to Spirit | `explicit.stat_3981240776` (amulet/chest; `stat_2704225257` on sceptres) |
| # to Level of all Skills | `explicit.stat_4283407333` |
| # to Level of all Minion / Spell / Melee / Projectile Skills | `stat_2162097452` / `stat_124131830` / `stat_9187492` / `stat_1202301673` |
| #% increased Attack Speed / Cast Speed | `explicit.stat_681332047` / `stat_2891184298` |
| #% increased Critical Hit Chance / Crit Damage Bonus | `explicit.stat_587431675` / `stat_3556824919` |
| #% increased Physical / Spell Damage | `explicit.stat_1509134228` / `stat_2974417149` |
| #% increased Elemental Damage with Attacks | `explicit.stat_387439868` |
| Adds # to # Physical / Fire / Cold / Lightning Damage | `stat_1940865751` / `stat_709508406` / `stat_1037193709` / `stat_3336890334` |
| # to Accuracy Rating | `explicit.stat_803737631` |
| Leech #% of Physical Attack Damage as Life | `explicit.stat_2557965901` |
| # Life Regeneration per second | `explicit.stat_3325883026` |
| #% increased Armour / Evasion | `explicit.stat_2866361420` / `stat_2106365538` |

Per-skill "+# to Level of all X Skills" use a shared hash with a suffix: `explicit.stat_448592698|<skill_number>` (grep stats.tsv for the skill name).

## Non-stat filter fields (complete)

`type_filters`: `category` (option — see below), `rarity` (option: `normal|magic|rare|unique|uniquefoil|nonunique`), `ilvl`, `quality` (min/max).

`equipment_filters` (all min/max): `damage`, `aps`, `crit`, `dps`, `pdps`, `edps`, `reload_time`, `ar`, `ev`, `es`, `ward` (Runic Ward), `block`, `spirit`, `rune_sockets` (Augmentable Sockets). Defence values include base+local mods+max quality.

`req_filters` (min/max): `lvl`, `str`, `dex`, `int`.

`map_filters` = UI "Endgame Filters" (min/max): `map_tier`, `map_packsize`, `map_magic_monsters` (Monster Effectiveness), `map_iir`, `map_rare_monsters` (Monster Rarity), `map_revives`, `map_bonus` (Waystone Drop Chance), `map_gold`, `map_experience`; option: `ultimatum_hint` (`Victorious|Cowardly|Deadly`).

`misc_filters`: min/max `gem_level`, `gem_sockets`, `area_level`, `stack_size`, `sanctum_gold` (Barya Sacred Water), `unidentified_tier`; true/false options: `identified`, `fractured_item`, `corrupted`, `sanctified`, `twice_corrupted`, `mutated` (Cultivated Vaal Unique), `veiled` (Unrevealed), `desecrated`, `crafted`, `foreseeing`, `mirrored`.

`trade_filters`: `account` (`{"input": "name"}`), `collapse` (option `"true"`), `indexed` (Listed within: `1hour|3hours|12hours|1day|3days|1week|2weeks|1month|2months`), `sale_type` (default omitted = Buyout/Fixed; `any|priced_with_info|unpriced`), `fee` (Gold Fee, min/max), `price` (min/max + option currency: omit = Exalted-equivalent, or `exalted_divine|exalted|divine|chaos|regal|vaal|alch|annul|aug|transmute|mirror`). Price semantics differ by mode: **option omitted** = the server converts every listing's price (any currency) to exalted-equivalent via internal exchange rates, then compares — use for "budget ≤ N ex" questions; **option set** = matches only listings literally priced in that currency, compared by that currency's amount (verified: `{"option":"divine","min":160,"max":170}` counts only divine-priced listings; an equivalent-mode `max` excludes items whose converted value exceeds it).

### Item categories (`type_filters.category.option`)

Weapons: `weapon` (any), `weapon.onemelee`, `.unarmed`, `.claw`, `.dagger`, `.onesword`, `.oneaxe`, `.onemace`, `.spear`, `.flail`, `.twomelee`, `.twosword`, `.twoaxe`, `.twomace`, `.warstaff` (Quarterstaff), `.talisman`, `.ranged`, `.bow`, `.crossbow`, `.caster`, `.wand`, `.sceptre`, `.staff`, `.rod`.
Armour: `armour` (any), `armour.helmet`, `.chest`, `.gloves`, `.boots`, `.quiver`, `.shield`, `.focus`, `.buckler`.
Accessories: `accessory`, `accessory.amulet`, `.belt`, `.ring`.
Gems: `gem`, `gem.activegem`, `.supportgem`, `.metagem`. Jewels: `jewel`. Flasks: `flask`, `flask.life`, `.mana`, `.charm`.
Endgame: `map` (any), `map.waystone`, `.fragment`, `.logbook`, `.breachstone`, `.barya`, `.bosskey` (Pinnacle Key), `.ultimatum`, `.tablet`.
Other: `card` (Divination Card), `sanctum.relic`, `currency`, `currency.omen`, `.socketable`, `.rune`, `.soulcore`, `.idol`.

### Item names / base types

Exact `name` (uniques) and `type` (bases) values: grep `references/items.tsv` (columns: `category<TAB>name<TAB>type<TAB>flags`; uniques have both name+type, bases only type). Bulk-exchange currency ids: `references/static.tsv`.

## Driving the UI instead (when asked to operate the page)

Layout: one **"Search Items..."** box on top; left column = six collapsible filter groups; right column = **Stat Filters**; bottom **Search** / **Clear** / **Hide Filters** buttons. Group headers toggle collapse — Type Filters starts open, the rest start collapsed (click the header text to expand before interacting).

- **Item name/base**: `fill` the "Search Items..." textbox → an autocomplete list appears grouped by category, first entry is always `"<text>" Custom Search` (raw term). Click a suggestion (e.g. **Temporalis** / Silk Robe sets name+type), or press Enter for term search.
- **Dropdown fields** (Item Category, Rarity, booleans, Listed, currency…): they are textboxes — click to open the option list, then click the option.
- **min/max fields**: two spinbuttons side by side (first=MIN, second=MAX); `fill` them directly.
- **Add a stat filter**: `fill` the **"+ Add Stat Filter"** textbox with mod text → autocomplete grouped by stat type (Pseudo, Explicit, …) → click the entry. A row appears with the mod name + min/max spinbuttons.
- **Stat group type**: the default group is **And**. Click **"+ Add Stat Group"** to add a group of another type: And / Not / If / Count / Weighted Sum / Weighted Sum v2. Count groups get an extra min box (the "at least N" count).
- **Run it**: click **Search**. The URL becomes `…/search/poe2/{league}/{query_id}` — grab the query_id from it. **Clear** resets the form.
- Snapshot after each step; refs churn as rows are added.

## Result rows (what you see / what it means)

Each listing shows price, seller, listed-age; "Instant Buyout"-eligible rows have a direct buy flow, others a whisper button. Sorting: click column headers, or set `sort` in the API body (`{"price":"asc"}` is the norm). In fetched API results `"gone": true` = already sold. Default page = first 10 hashes; UI lazy-loads more (API: fetch in batches of ≤10).

## Knowledge base (`knowledge/` — retrieve on demand, don't preload)

`knowledge/` in this skill dir accumulates experience-type facts that raw API data can't tell you — mod slot availability (which slots a mod can actually roll on), market price wisdom, complex-query tricks. It grows over many sessions, so **don't read it all**: grep `knowledge/INDEX.md` (or the whole dir) with keywords from the user's request — try both 中文 and English terms — and read only the file(s) that hit.

Consult it **before building a query** whenever the request involves a specific mod+slot combination or a "how much is X worth" judgement; if the KB says a combo is impossible (e.g. Spirit on gloves), tell the user instead of running a doomed search.

When the user teaches a new fact (slot restriction, premium combo, query trick), append it to the matching `knowledge/*.md` (create a new category file if none fits), verify any stat ids against `references/stats.tsv`, and add a keyword line to `INDEX.md` — bilingual keywords so future greps hit.

## Gotchas

- `/api/trade2/data/*` (stats/items/static/filters) sits **behind Cloudflare** — plain curl/httpx returns an HTML challenge. Fetch in-page (or reuse the TSVs here). The search/fetch APIs (`/api/trade2/search`, `/fetch`) work fine with plain HTTP + POESESSID.
- In-page `eval` fetch output is a **double-encoded** JSON string — decode twice.
- Some mod texts map to **multiple ids** (e.g. "# to all Attributes", "# to Spirit" differ by item class). If a search errors or misses, try the sibling id or the pseudo stat.
- Filter group key is `map_filters` in JSON even though the UI calls it "Endgame Filters".
- Search totals cap at 10000; narrow the query if you need everything.
- League name in the URL path must be URL-encoded (`Runes%20of%20Aldur`); read the current league from `setting.py`.
- Reference TSVs are a league snapshot (captured 2026-07, Runes of Aldur). Regenerate in-page after big patches.
