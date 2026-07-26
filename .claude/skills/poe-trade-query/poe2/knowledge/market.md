> ⛔ **POE2 ONLY** ｜ 遊戲版本：**POE2 0.5 "Runes of Aldur"** ｜ 最後整理：**2026-07-27**（各條事實的日期見檔內逐條標註）
> 以下組合、價格與基底名稱**只適用 POE2**。若 `REALM=poe1`，停止並改讀 `../../poe1/`。
> 行情會隨聯盟漂移——引用前先看逐條日期，過期的當參考值不當事實。

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

2026-07 (Runes of Aldur), joint solve for **F82/C118/L116 + Spirit 73 + MS30**, maximizing mana_eq (ES+mana+2×attr+40×%incmana). Budget curve from properly-probed pools (see [`../../common/tricks.md`](../../common/tricks.md) "Probe the ceiling"): **~31d → 2476 (budget floor), ~59d → 3073 (CP sweet spot), ~119d → 3165 (top)**. An earlier cheap-end-only sampling wrongly concluded the curve was flat after 35d — that was sampling bias, not market reality.

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

### 2026-07-08 structure upgrade: move ALL res off the rings (user-directed, verified +~290 mana_eq)

The table above (rings carry res) is the INFERIOR structure. Re-solve on the same market snapshot with res shifted to belt/boots and rings left res-free: **119d → 3638 mana_eq** (vs ~3348 with res-carrying rings; every budget tier gained 150-300). Query design implication: ring pools must include a **no-res pure-mana segment** (inc6% + flat mana 230/270 pseudo-total tiers — 597 listings ≤120d, deep market) or the optimizer literally cannot discover this; res-only-on-rings pool designs are self-defeating.

Anchors for the winning structure (2026-07-08):
| piece | spec | price |
|---|---|---|
| Ring | Mnemonic base, 240+ mana, 15-16% inc, ~55 attr, 40% qual, NO res | 29–30 div |
| Belt | flat mana ~99–124 + **130+ total res** (the res anchor slot) | 5–15 div |
| Boots | MS30+ + Spirit 15 + res 60–120 + flat mana ~104–108 (low ES ok) | 55 ex – 12 div |
| Helmet | ES ~510–520 + 1 res + int/mana | 3 div |
| Chest | Spirit 58 + ES ~680–745 + 1-2 res (corrupted) | 30 div |

Boots/belt carrying both res AND flat mana is what frees the budget; the two Mnemonic rings alone ≈ 1800 mana_eq for 59d. Dual-res desecrated lines ("+#% to X and Chaos Resistances") count toward ele res — make sure the parser reads them.

### 2026-07-09 re-solve (same constraints, fresh snapshot): market improved, top now 107d → 3681

Budget curve 59d→3289 / 77d→3540 / 96d→3599 / **107d→3681 (ceiling — 119d best was only 3659, so spending past 107d bought nothing)**. Converged at cap 50k (=100k identical; jewelry side saturated at 35.7k groups). What moved vs 07-08: chestD-tier supply recovered (ES780+ Spirit57+: 14 → 713 listings), and the winning belt was a **corrupted 5d Heavy Belt with C116/L64 + mana 89** — a corrupted mono-res-stacked belt beat the uncorrupted mana120+res tier on price by 6×. The 40%-mana-quality Mnemonic rings (~235-246 flat + 15-16% inc + ~55 attr) held steady at 29-30d; a 25d tier (231 flat, 31 attr, +1 res) exists. Cheap corrupted ES boots (MS30+Spirit14+2res, 1d) remain the best CP slot — check bootsB-style pools first.

### Bucket-cap convergence sweep for this six-slot case (2026-07 實測，pure Python, desktop)

Measured on the six-slot solve above — these are **this case's** numbers, not a universal setting (the method is in [`../../common/tricks.md`](../../common/tricks.md) "Multi-slot gear combos"):

| `prune_groups` cap | runtime | result |
|---|---|---|
| 4000 | ≈1 min | lost 0.6% on one mid tier; headline tiers (sweet spot / max budget) already exact |
| 20000 | ≈2 min | small residual loss |
| **50000** | **89 s** | **converged** — identical to 100k |
| 100000 | 14 min | identical to 50k |
| 200000 | 45 min | fully-saturated finest-granularity bucketing (effective no-loss backstop) |

Kept-counts saturate at the finest bucket pass (here **armour 84k, jewelry 157k** groups), so caps beyond that change nothing. The 07-09 re-solve saturated its jewelry side at 35.7k groups.
