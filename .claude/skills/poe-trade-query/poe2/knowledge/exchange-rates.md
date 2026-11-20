> ⛔ **POE2 ONLY** ｜ 遊戲版本：**POE2 0.5 "Runes of Aldur"** ｜ 最後整理：**2026-07-27**（各條事實的日期見檔內逐條標註）
> ⚠ **poe2scout 並非 POE2 專屬，它同時服務兩款遊戲**（路徑段是 RealmApiId，POE2 是 `poe2`）——本檔只有幣別體系（exalted 為基準）與讀數是 POE2 專屬。
> POE1 的對應檔是 `../../poe1/knowledge/exchange-rates.md`。若 `REALM=poe1`，停止並改讀那裡。
> 「**查價一律走 poe2scout，不要用交易站 exchange 掛牌**」是兩款遊戲共通規則，見 [`../../common/tricks.md`](../../common/tricks.md)。

> 🔁 **2026-11-20 改版：匯率與通貨查價改走 `poe-currency-price` skill**（`.claude/skills/poe-currency-price/cx.py --realm poe2`，
> 讀 GGG 官方公開的 Currency Exchange API）。**本檔以下的 poe2scout 做法已停用，只留作歷史紀錄。**
> 仍然成立的結論：不要猜匯率、不要用交易站掛牌板；同一種通貨在不同交易對算出來的價格會不一樣
> （2026-11-20 Forbidden Rites 實測：div|ex 市場一小時只成交 164 div、匯率在 418–522 ex 間跳，
> div|chaos 市場一小時成交 14,022 div、穩定在 11.7 c——div 與 chaos 互換要讀直接市場，別用兩個 ex 匯率相除。
> 使用者說明：當時賽季快結束、基本上沒有玩家，市場不流動導致價格奇怪是正常的，不代表 POE2 平常如此）。

# Currency exchange rates — how to get real market rates (通貨匯率查詢)

Whenever a task needs a currency conversion (budget in divine, prices in exalted, "what's X worth"), get the rate from here — do NOT guess and do NOT use the trade-site listing board.

## The go-to recipe: poe2scout SnapshotPairs

Republishes GGG's official `service:cxapi` hourly in-game Currency Exchange trade data. No auth, plain HTTP (send a full browser UA):

```bash
curl -s -H "User-Agent: <full browser UA>" \
  "https://poe2scout.com/api/poe2/Leagues/{LEAGUE}/SnapshotPairs" > pairs.json
```

Returns ~2200 pair objects. Each has `CurrencyOne`/`CurrencyTwo` (with `ApiId` like `divine`, `chaos`, `exalted`) and `CurrencyOneData`/`CurrencyTwoData` with:

- `RelativePrice` — that currency's traded value **in exalted** (volume-weighted, per this pair's market)
- `VolumeTraded`, `StockValue`, `HighestStock`

Extract the big-three rates:

```python
import json
want = {"exalted", "divine", "chaos"}
for x in json.load(open("pairs.json")):
    a, b = x["CurrencyOne"]["ApiId"], x["CurrencyTwo"]["ApiId"]
    if a in want and b in want:
        print(a, x["CurrencyOneData"]["RelativePrice"], "|", b, x["CurrencyTwoData"]["RelativePrice"])
# cross rate: div-in-chaos = div.RelativePrice / chaos.RelativePrice (from the chaos|divine pair)
```

Notes:
- Snapshots are hourly (`GET .../ExchangeSnapshot` → current `Epoch`; source has ~5 min delay).
- `RelativePrice` is per-pair: the same currency can differ slightly between pairs (e.g. divine 709.6 in divine|exalted vs 804.8 in chaos|divine at one reading — the latter reflects that pair's own trades). For a headline rate use the pair against exalted; for cross rates divide within one pair.
- Prefer high-`VolumeTraded` pairs; thin pairs are noisy.
- Other routes: `/api/Realms` (realm ids), `.../Currencies/ByCategory`, per-pair history `.../Currencies/Pairs/{id1}/{id2}/History`. ~~OpenAPI spec~~ 已失效（2026-09-09 實測 `/api/openapi.json` 回 404、`/openapi.json` 回 SPA 殼頁）；端點挖法見 [`../../common/tricks.md`](../../common/tricks.md)。

Reference reading 2026-07 (Runes of Aldur), verified against the user's in-game screen (690–710): **1 div = 709.6 ex, 1 chaos ≈ 108 ex, 1 div ≈ 7.46 chaos**.

## Alternative & rejected sources

- **Official Currency Exchange API** — ~~requires OAuth scope `service:cxapi`~~ **outdated.** Since POE1 3.29.0 (2026-07-21) GGG serves it as a Public API at `https://web.poecdn.com/api/currency-exchange[/<realm>]/<epoch>` with no login (verified 2026-11-20). It is now the primary source — use the `poe-currency-price` skill.
- **Trade-site `POST /api/trade2/exchange/...` listing board — UNRELIABLE for rates.** A thin manual-listing board, not the in-game matching market: observed asks 550–600 ex/div vs true 710 (-15~20%), huge bid/ask spreads, bait listings (great ratio, stock 1) at the top. Only use it to see what's listed for direct website trade.

Related: the trade search's exalted-equivalent price cap uses yet another (hidden, lagging) internal rate — see [api-quirks.md](api-quirks.md) and [`../../common/tricks.md`](../../common/tricks.md).

*(established 2026-07: user cross-checked poe2scout against the in-game Currency Exchange — matched)*
