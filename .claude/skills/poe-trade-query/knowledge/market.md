# Market knowledge (行情 / 極品組合)

Which mod combos are market-premium. Use to set price expectations and to warn the user before an expensive search; offer relaxed fallbacks alongside.

## Amulet: +3 all Spell Skills + Spirit (項鍊雙極品綴)

**"+3 to Level of all Spell Skills" + "# to Spirit"** on one amulet = top-tier (GG-priced) caster item:

```json
"stats": [{ "type": "and", "filters": [
  { "id": "explicit.stat_124131830", "value": { "min": 3 } },
  { "id": "explicit.stat_3981240776", "value": { "min": 1 } }
]}]
```

Warn the user about the price tier; offer a relaxed fallback (+2, or drop the Spirit min) alongside.

*(taught by user 2026-07)*

## Lament Amulet: Cast on Minion Death base + spells/Spirit (哀慟項鍊)

"Grants Skill: Level # Cast on Minion Death" on an amulet = the **Lament Amulet base's inherent grant** — filter with `skill.cast_on_minion_death` (the `skill.*` stat group matches base-granted skills; the base also carries a fixed "-1 Prefix Modifier allowed"). Combined with "+N to Level of all Spell Skills" + Spirit, observed prices 2026-07 (Runes of Aldur, instant-buyout):

| tier | price |
|---|---|
| +3 spell skills | 110–150 div (few listings) |
| +4 spell skills (bulk of market) | 200–400 div |
| +4 top rolls / high ilvl | up to ~2000 div |

Spirit rolls 41–50 are common on these; the spell-skill tier moves price far more than the Spirit roll. Almost all listings are finished +4 items.

## MOM/EB three-piece (helm/chest/boots) price anchors (MOM/EB 三件套行情)

Reference points 2026-07 (Runes of Aldur), for ES-stacking builds (EB: gear ES ≡ mana; +Int counts ×2 mana). ES/Spirit armour is **much cheaper than intuition suggests** — corrupted pieces especially:

| piece | spec | price |
|---|---|---|
| Chest | Spirit 57–59, ES ~500–550 (often corrupted) | < 1–4 div |
| Chest | Spirit 60, ES ~715 | ~29 div |
| Chest | Spirit 60, ES ~770 + res/int | ~58 div |
| Chest | Spirit 59, ES ~800 (top of ladder) | ~98 div |
| Helmet | ES 400–440 tiara + 40+ total res + int/mana | 15–35 exalted (!) |
| Boots | 30% MS + crafted Spirit 14 + ES ~240–290 + res/int | 2 chaos – 2 div |

Notes: the chest ES ladder shows hard diminishing returns past ~ES 770 (98d buys +2 mana-eq over 58d). Helmets are the free slot — dump res/int/mana needs there. A full three-piece meeting F42/C29/L13 + Spirit 73 + MS30 was solvable at **~4 div** (budget floor) and optimal at **~58–60 div**.

## MOM/EB six-piece (helm/chest/boots/2 rings/belt) anchors (六件套行情)

2026-07 (Runes of Aldur), joint solve for **F82/C118/L116 + Spirit 73 + MS30**, maximizing mana_eq (ES+mana+2×attr+40×%incmana). Budget curve from properly-probed pools (see tricks.md "Probe the ceiling"): **~31d → 2476 (budget floor), ~59d → 3073 (CP sweet spot), ~119d → 3165 (top)**. An earlier cheap-end-only sampling wrongly concluded the curve was flat after 35d — that was sampling bias, not market reality.

Slot anchors:
| piece | spec | price |
|---|---|---|
| Chest | Spirit 59, ES ~777, int (corrupted) | ~25 div (Spirit57+ ES780+ is the ceiling: only ~14 listings under 96d) |
| Helmet | ES ~500–520 + int (+small res) | 3–4 div |
| Helmet | ES ~563–570 + mana + 80+ total res | 50–65 div |
| Boots | MS30 + crafted Spirit 15 + ES ~320 + int | ~15 div |
| Boots | MS30 + crafted Spirit 13-14 + ES ~120–220 + res | 2–3 div |
| Ring | **triple-stat: 6%incMana + ~200+ flat mana + 2 res + int** | **8–15 div** (huge value: ~600 mana_eq each; ring ceiling is high — inc6+mana175+res80 still had 727 listings <96d) |
| Ring | 6-7%incMana + 2 res + int (no big flat mana) | 1–5 exalted |
| Belt | flat mana ~117–124 + res ~70 + int | 1–2 exalted |
| Belt | mana 120+ AND 125+ total res | ~30 div (rarely worth it) |

Lessons: rings are where budget scales best (the % + flat mana + res triple exists in depth); chest Spirit+ES is the mandatory anchor cost; belts stay cheap unless you force mana+high-res on one item.
