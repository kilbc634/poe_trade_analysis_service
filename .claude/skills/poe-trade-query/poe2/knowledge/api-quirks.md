> ⛔ **POE2 ONLY** ｜ 遊戲版本：**POE2 0.5 "Runes of Aldur"** ｜ 最後整理：**2026-07-27**（各條事實的日期見檔內逐條標註）
> 以下欄位名、回傳格式、幣別與實測數字**只適用 POE2**。若 `REALM=poe1`，停止並改讀 `../../poe1/`。

# POE2 API field & parsing quirks (POE2 欄位名與回傳格式陷阱)

The realm-agnostic transport rules live in [`../../common/tricks.md`](../../common/tricks.md). This file holds the parts of them that are **bound to POE2's schema** — split out 2026-07-27 so they can't leak into POE1 work.

## `equipment_filters.es` (and `ar`/`ev`) is the max-quality value (防禦數值按滿品質計)

POE2 puts defence min/max filters in **`equipment_filters`**. They compare against base + local mods **+ 20% quality**, not the item's current sheet value. A search for `es >= 600` can return items currently showing ES ~500 (needs quality currency to reach 600). When reporting results, flag items whose current value is below the user's threshold.

## Fetch API mod entries are mixed string/object (詞綴回傳格式不一)

`item.explicitMods` etc. can contain plain strings **or** objects `{description, hash, mods:[{name, tier, level, magnitudes}]}`. Normalize with `typeof m === 'string' ? m : m.description`. Bonus: the object form's `tier`/`magnitudes` tells you the mod's tier and roll range — useful for judging whether a roll is near its cap without leaving the result set.

More fetch-parsing facts (2026-07):
- Mod text embeds wiki-link brackets: `+12 to [Spirit|Spirit]`, `[EnergyShield|Energy Shield]` — strip with regex `\[([^\[\]|]*\|)?([^\[\]]*)\]` → `\2` before matching.
- Crafted mods appear **inside `explicitMods`** with `flags: {crafted: true}` (hash `stat.crafted.…`), not in a separate `craftedMods` array.
- The item's current defence numbers live in `item.extended` (`es`, `ev`, `ar`) — no need to parse `properties`.
- `runeMods` starting with `Bonded:` (raw tag `[ShamanOnlyMods|Bonded]`): **Bonded is not a rune type** — the Shaman ascendancy gains extra effects from every socketed rune, and the `Bonded:` line is that extra effect. The same rune's *normal* effect appears as its own separate line (and defence-type effects are already baked into `extended.es`). Scoring rule: for non-Shaman buyers exclude only the `Bonded:` lines and count everything else as usual; the sockets are NOT wasted — they hold normally-working runes.
- **Corrupted items CAN swap runes** (user-confirmed 2026-07): corruption locks the *number* of rune sockets, not their contents. So when valuing a corrupted item, treat every rune socket as "replaceable with the best rune for the build" — a bad rune (e.g. a useless Bonded) is not dead weight, but a *missing* socket can never be added. What corruption does forbid: further crafting/modification and adding quality.

*(learned 2026-07 during a Spirit+ES chest price hunt)*

## Exalted-equivalent price cap diverges from market rate (等值價格上限的匯率偏差)

POE2's equivalent-mode base currency is **exalted**. Observed 2026-07 (Runes of Aldur): a `max: 17000` cap let through items priced up to 52 div → internal rate ≤ ~327 ex/div (an upper bound only; bisect the cap if a precise value ever matters), while the true traded rate was ~710 ex/div. **So the equivalent-mode cap can be off by more than 2×.**

Mechanism and the general rule: [`../../common/tricks.md`](../../common/tricks.md) → "The price cap's equivalent mode". Real POE2 rates: [`exchange-rates.md`](exchange-rates.md).

## Search result window: 100 hashes (POE2 verified)

A POE2 search response stores up to **100** result hashes; `[40:100]` is the pricier tranche for deep-fetching. Fetch batches cap at **10** hashes per call. (Method: `../../common/tricks.md` → "Deep-fetch a search's price ladder".)
