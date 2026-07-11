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

Body armour Spirit roll cap: top prefix tier is **"Queen's" P1 = 57–61** (observed 2026-07). So "Spirit ≥ 57" already targets the top tier — price differences among matches come from ES / resists / corruption, not from higher Spirit.

Boots crafted Spirit values (observed 2026-07): the common craft is **"of the Stars" S0 = 10–15** — boots with 12–15 are plentiful and cheap (from a few chaos). Values **16–18 exist but are rare and expensive** (7–100+ div, often on otherwise-bad bases). So a "≥73 total Spirit" plan should assume chest 57–61 + boots 12–15; corrupted-implicit-Spirit helmets with usable ES effectively don't exist on the market (searched ES≥200 → 0 results).

## Mana roll caps on jewelry (戒指/腰帶魔力詞綴上限, user-taught 2026-07)

- Ring: besides `#% increased maximum Mana` (top explicit roll 6% → 7% with 20% Mana-Modifiers quality), rings also roll big **flat** `+# to maximum Mana` — observed listings around **+165, top roll ~179**. Weaker per-point than the % mod (at ~3500 total mana, 6% ≈ 210; basis corrected from 4000 on 2026-07-11, see mechanics.md) but a real chase stat: a GG ring carries BOTH.
- Belt: flat mana top tier is **+(105–124)**. Alternatively belts can go pure-resistance (130%+ total ele res) to relieve res pressure on other slots — both directions are valid; let the joint optimizer decide.

## Attributes on pure-ES base armour (純ES基底的能力值詞綴)

The natural affix pool of **pure ES bases has only `+# to Intelligence`** — no Strength, no Dexterity, no all-attributes rolls (taught by user 2026-07, from the affix tables). Sole exception: **desecrated mods (深淵詞綴)**, when revealed, can give dual-attribute lines like `+15 to Strength and Intelligence` / `+15 to Strength and Dexterity` — but these are considered junk reveals, usually a byproduct of someone's own crafting, and such items barely circulate (bad listing appeal). Practical query rule: on ES armour, filter/score attributes via Int only; don't bother adding str/dex/all-attr stat ids for those slots. (Attribute-flexible valuation ×2 still applies where attributes DO roll — amulets, rings, belts; see mechanics.md.)

*(taught by user 2026-07, ids verified against references/stats.tsv)*
