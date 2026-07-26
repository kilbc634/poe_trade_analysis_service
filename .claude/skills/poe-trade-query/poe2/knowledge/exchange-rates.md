> ⛔ **POE2 ONLY** ｜ 遊戲版本：**POE2 0.5 "Runes of Aldur"** ｜ 最後整理：**2026-07-27**（各條事實的日期見檔內逐條標註）
> poe2scout 是 POE2 專屬資料源，幣別體系（exalted 為基準）也是 POE2 的。
> POE1 的匯率來源另尋，寫進 `../../poe1/knowledge/`。若 `REALM=poe1`，停止並改讀那裡。

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
- Other routes: `/api/Realms` (realm ids), `.../Currencies/ByCategory`, per-pair history `.../Currencies/Pairs/{id1}/{id2}/History`. OpenAPI spec: `https://poe2scout.com/api/openapi.json`.

Reference reading 2026-07 (Runes of Aldur), verified against the user's in-game screen (690–710): **1 div = 709.6 ex, 1 chaos ≈ 108 ex, 1 div ≈ 7.46 chaos**.

## Alternative & rejected sources

- **Official `GET api.pathofexile.com/currency-exchange/poe2`** — the upstream (hourly `volume_traded`, `lowest/highest_ratio` per market). Requires OAuth scope `service:cxapi` (approved apps only; apply via oauth@grindinggear.com). POESESSID and POETOKEN are both rejected (401/403) — don't retry them. Worth applying for if this project wants first-party data.
- **Trade-site `POST /api/trade2/exchange/...` listing board — UNRELIABLE for rates.** A thin manual-listing board, not the in-game matching market: observed asks 550–600 ex/div vs true 710 (-15~20%), huge bid/ask spreads, bait listings (great ratio, stock 1) at the top. Only use it to see what's listed for direct website trade.

Related: the trade search's exalted-equivalent price cap uses yet another (hidden, lagging) internal rate — see [api-quirks.md](api-quirks.md) and [`../../common/tricks.md`](../../common/tricks.md).

*(established 2026-07: user cross-checked poe2scout against the in-game Currency Exchange — matched)*
