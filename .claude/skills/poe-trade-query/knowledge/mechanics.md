# Item & build mechanics that drive valuation (裝備數值機制與估值)

Game-mechanic facts (user-taught) that change how listings should be scored. Consult when ranking/comparing items, not just querying.

## Item ES total formula (裝備ES計算式，user-confirmed 2026-07)

```
ES總值 = (基底ES × 品質倍率(Q20=1.2) + "+# to maximum Energy Shield" 詞綴)
       × (1 + Σ "n% increased Energy Shield" 詞綴 + Σ "n% increased ES" 符文)
```

Implications:
- `%increased ES` runes multiply in the **final zone** → a "20% increased ES" rune usually beats a "+50 maximum Mana" rune on any decent-ES piece.
- Sellers of high-ES gear usually **pre-socket 20% ES runes** to make the listing look good — so `extended.es` on listings is typically already rune-optimized; only an item with genuinely *empty* sockets has hidden upside via rune insertion. (A `Bonded:` line does NOT mean a wasted socket — it's the Shaman-ascendancy bonus effect of a normally-working rune; see tricks.md.)
- **Corrupted = quality locked.** A currency exists that re-rolls quality on corrupted gear but it randomly raises/lowers and can destroy the item — treat listed ES on corrupted items as final. (Rune contents remain swappable; socket *count* is locked — see tricks.md.)

## MOM/EB mana valuation (user-confirmed 2026-07)

- **EB (Eldritch Battery)** converts ALL flat max ES (each item's final ES from the formula above) into flat max mana **first**; the summed flat mana is then scaled by "%increased maximum Mana". Tree "%increased maximum ES" nodes are **dead** after EB — they would scale flat ES, which was already converted away.
- Therefore for EB builds: **1 gear-ES = 1 mana, exactly** — no weighting needed either way.
- **+Intelligence = +2 max mana** (inherent). Str/Dex/all-attributes count the same ×2 in practice: the tree has many "+5 attribute (choose one)" nodes on mandatory paths, so players rebalance gear attributes into Int freely. (Note: on pure-ES armour bases only Int actually rolls — see slots.md; the ×2-any-attribute rule matters on amulets/rings/belts.)
- Useful armour runes for ES/mana builds: `+50 to maximum Mana`, `20% increased Energy Shield` (usually the better pick per the formula), and helmet-only `3% increased maximum Mana`.
- Scoring formula used successfully for gear comparison: `mana_eq = ES + flat_mana + 2×(int+str+dex+all_attr)`; "Life" mods are worthless to MOM/EB.
- **Rings ×2 + belt are the pressure valves** (user 2026-07): those slots have no ES concern — they carry flat mana + resistances, and they're simple/cheap. Common practice: shift resistance requirements onto rings/belt to free the helm/chest affix budget for pure ES. So a full-outfit optimization should ideally solve helm/chest/boots/rings/belt **jointly** — a 3-piece solve that forces all res onto helm/chest is over-constrained.
