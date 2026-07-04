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
