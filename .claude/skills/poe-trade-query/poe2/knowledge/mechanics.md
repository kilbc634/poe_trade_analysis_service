> ⛔ **POE2 ONLY** ｜ 遊戲版本：**POE2 0.5 "Runes of Aldur"** ｜ 最後整理：**2026-07-27**（各條事實的日期見檔內逐條標註）
> ES/EB/MOM 計算式、符文、觸媒品質、屬性換算**只適用 POE2**。POE1 有同名但不同效果的機制，
> 一律不得沿用。若 `REALM=poe1`，停止並改讀 `../../poe1/`。

# Item & build mechanics that drive valuation (裝備數值機制與估值)

Game-mechanic facts (user-taught) that change how listings should be scored. Consult when ranking/comparing items, not just querying.

## Item ES total formula (裝備ES計算式，user-confirmed 2026-07)

```
ES總值 = (基底ES × 品質倍率(Q20=1.2) + "+# to maximum Energy Shield" 詞綴)
       × (1 + Σ "n% increased Energy Shield" 詞綴 + Σ "n% increased ES" 符文)
```

Implications:
- `%increased ES` runes multiply in the **final zone** → a "20% increased ES" rune usually beats a "+50 maximum Mana" rune on any decent-ES piece.
- Sellers of high-ES gear usually **pre-socket 20% ES runes** to make the listing look good — so `extended.es` on listings is typically already rune-optimized; only an item with genuinely *empty* sockets has hidden upside via rune insertion. (A `Bonded:` line does NOT mean a wasted socket — it's the Shaman-ascendancy bonus effect of a normally-working rune; see [api-quirks.md](api-quirks.md).)
- **Corrupted = quality locked.** A currency exists that re-rolls quality on corrupted gear but it randomly raises/lowers and can destroy the item — treat listed ES on corrupted items as final. (Rune contents remain swappable; socket *count* is locked — see [api-quirks.md](api-quirks.md).)

## MOM/EB mana valuation (user-confirmed 2026-07)

- **EB (Eldritch Battery)** converts ALL flat max ES (each item's final ES from the formula above) into flat max mana **first**; the summed flat mana is then scaled by "%increased maximum Mana". Tree "%increased maximum ES" nodes are **dead** after EB — they would scale flat ES, which was already converted away.
- Therefore for EB builds: **1 gear-ES = 1 mana, exactly** — no weighting needed either way.
- **+Intelligence = +2 max mana** (inherent). Str/Dex/all-attributes count the same ×2 in practice: the tree has many "+5 attribute (choose one)" nodes on mandatory paths, so players rebalance gear attributes into Int freely. (Note: on pure-ES armour bases only Int actually rolls — see slots.md; the ×2-any-attribute rule matters on amulets/rings/belts.)
- Useful armour runes for ES/mana builds: `+50 to maximum Mana`, `20% increased Energy Shield` (usually the better pick per the formula), and helmet-only `3% increased maximum Mana`.
- Scoring formula used successfully for gear comparison: `mana_eq = ES + flat_mana + 2×(int+str+dex+all_attr) + 35×(%incmana)`; "Life" mods are worthless to MOM/EB.
- **"#% increased maximum Mana" basis = ~3500 total mana, so 1% ≈ 35 mana_eq** (user-corrected 2026-07-11 after completing the six-piece buy: the finished character's base mana pool landed near 3500, not the earlier rough 4000 guess — the old 40/1% factor overvalued %incmana by ~14%). Combos scored before 2026-07-11 (incl. all market.md anchors) used the 40/1% basis; don't compare their mana_eq numbers 1:1 against new runs.
- **Rings ×2 + belt are the pressure valves** (user 2026-07): those slots have no ES concern — they carry flat mana + resistances, and they're simple/cheap. Common practice: shift resistance requirements onto rings/belt to free the helm/chest affix budget for pure ES. So a full-outfit optimization should ideally solve helm/chest/boots/rings/belt **jointly** — a 3-piece solve that forces all res onto helm/chest is over-constrained.
- **Quality (Mana Modifiers) catalysts are RING-ONLY — belts CANNOT take quality** (user-corrected 2026-07-08 after a run scored belts as catalyzable). Belt mana mods: always take the displayed value as-is.
- **Ring quality valuation — the user's full 3-case rule (2026-07-09).** The buyer re-catalysts every viable ring to +20% mana quality, so score accordingly. No adjustment when: corrupted (locked), or mana quality already ≥20% (special crafts exceed the base-20 cap — +36/40/60% observed on uncorrupted rings; displayed = final). Convert when uncorrupted and:
  1. *no quality*: mana mods × 1.2, floored.
  2. *non-mana quality q%*: re-catalysting WIPES it — mods that quality was boosting revert to raw (`floor(value/(1+q))`), then mana mods × 1.2. Verified boost scope of an elemental catalyst (vs tier magnitude ranges in fetch JSON): its element's single-res line, its element's "X and Chaos Resistances" dual line, and **"+#% to all Elemental Resistances"** (all-res reverts for ALL three elements). Attribute-type quality EXISTS and boosts every attribute mod (str/dex/int/all-attr) — but user-confirmed 2026-07-09 it's safe to ignore: nobody applies it in practice (poor value), so listings virtually never carry it.
  3. *mana quality q% < 20*: `floor(value/(1+q) × 1.2)` on mana mods.
  Tip: fetch JSON carries each mod's tier roll range (`explicitMods[].mods[].magnitudes`) — displayed > tier max is how you detect quality-boosted lines empirically (beware false positives from two merged same-stat mods).
- **Mnemonic Ring base = the MOM/EB premium ring base**: implicit `8% increased maximum Mana` (7% seen at lower quality). Market 2026-07: 240+ flat mana + 15-16% total inc + ~50 attrs + 40% quality ≈ **29-30 div** — roughly 900-1000 mana_eq per ring, the single densest mana source of any slot.
