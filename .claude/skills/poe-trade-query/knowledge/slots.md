# Mod slot availability (詞綴部位分佈)

Which slots a mod can actually roll on. Check before building a query — if the user asks for a mod on a slot that can't have it, explain the real sources instead of running a search that returns nothing.

## Spirit (精魂)

Gear Spirit comes from very few places. There is **no pseudo total-Spirit stat**, so each source needs its own group-prefixed id:

| source | how | query |
|---|---|---|
| Amulet 項鍊, Body Armour 胸甲 | normal explicit roll | `explicit.stat_3981240776` |
| Sceptre 權杖 | weapon-inherent Spirit (own id!) | `explicit.stat_2704225257`, or `equipment_filters.spirit` for the base value |
| Helmet 頭盔 | **corrupted implicit only** (腐化額外詞綴) — rare & pricey | `implicit.stat_3981240776` + `misc_filters.corrupted: {"option":"true"}` |
| Boots 鞋子 | **crafted mod (工藝詞綴), new in Runes of Aldur league** | `crafted.stat_3981240776` |

Gloves / belts / rings **cannot roll Spirit** — don't search for it there. (Runes `rune.stat_3981240776` also exist for socketed augments.)

*(taught by user 2026-07, ids verified against references/stats.tsv)*
