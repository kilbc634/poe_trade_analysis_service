> ⛔ **POE1 ONLY** ｜ 聯盟：**Allflame** ｜ 最後整理：**2026-07-28**
> 以下路徑、基準幣別與行情**只適用 POE1**。若 `REALM=poe2`，停止並改讀 `../../poe2/knowledge/exchange-rates.md`。
> ⚠ 下面「2026-07-27 讀數」那張表**已經過期**——07-28 實測 1 div = 120.70c，一天漂了 +19%。**表裡的數字只能當形狀看，任何換算都要照下面的方法重抓。**

# 通貨匯率 — POE1 怎麼拿真實市場價

poe2scout 雖然名字叫 poe2，但**同時服務 POE1**。要換算就從這裡拿，不要用猜的，也不要用交易站的通貨掛牌板。

## 關鍵：路徑段是 RealmApiId，不是遊戲名

先看 realm 清單：

```bash
curl -s -H "User-Agent: <full browser UA>" "https://poe2scout.com/api/Realms"
```

```jsonc
[{"Value":"poe1/pc",  "GameApiId":"poe",  "RealmApiId":"pc",   "TradeApiPath":"trade"},
 {"Value":"poe1/xbox","GameApiId":"poe",  "RealmApiId":"xbox", "TradeApiPath":"trade"},
 {"Value":"poe1/sony","GameApiId":"poe",  "RealmApiId":"sony", "TradeApiPath":"trade"},
 {"Value":"poe2/poe2","GameApiId":"poe2", "RealmApiId":"poe2", "TradeApiPath":"trade2"}]
```

API 路徑吃的是 **`RealmApiId`**，所以 PC 版 POE1 是 **`/api/pc/...`**。這點很容易踩錯：`/api/poe1/...`、`/api/poe/...` 都回 `400 "Invalid realm."`，`/api/poe1/pc/...` 回 404。

| | 路徑 |
|---|---|
| POE1 (PC) | `https://poe2scout.com/api/pc/...` |
| POE1 (Xbox / PS) | `.../api/xbox/...`、`.../api/sony/...` |
| POE2 | `.../api/poe2/...` |

## 取匯率

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"

# 1) 聯盟清單（含 IsCurrent、基準幣別、頭條匯率）
curl -s -H "User-Agent: $UA" "https://poe2scout.com/api/pc/Leagues"

# 2) 完整成交配對
curl -s -H "User-Agent: $UA" "https://poe2scout.com/api/pc/Leagues/Allflame/SnapshotPairs" > pairs.json
```

`/Leagues` 每個聯盟直接帶 `IsCurrent`、`BaseCurrencyApiId`、`DivinePrice`、`ChaosDivinePrice` —— **只要頭條匯率的話這支就夠了，不必抓 SnapshotPairs**。

`SnapshotPairs`（Allflame 實測 1366 組）每組有 `CurrencyOne`/`CurrencyTwo`（`ApiId` 如 `chaos`/`divine`）與各自的 `RelativePrice`、`VolumeTraded`：

```python
import json
want = {"chaos", "divine", "exalted", "mirror"}
for x in json.load(open("pairs.json")):
    a, b = x["CurrencyOne"]["ApiId"], x["CurrencyTwo"]["ApiId"]
    if a in want and b in want:
        print(a, x["CurrencyOneData"]["RelativePrice"],
              "|", b, x["CurrencyTwoData"]["RelativePrice"],
              "| vol", x["CurrencyOneData"]["VolumeTraded"])
```

⚠ **`RelativePrice` 的計價單位是該聯盟的 `BaseCurrencyApiId`。POE1 是 chaos**（跟交易站 `price` 省略 option 時的 "Chaos Orb Equivalent" 一致）。取交叉匯率時在同一組配對內相除，別跨組混用。挑 `VolumeTraded` 高的組，冷門組雜訊大。

## 2026-07-27 Allflame 讀數（⚠ 已過期，見檔頭；最新讀數在 [market.md](market.md)）

| 配對 | 讀數 | 成交量 |
|---|---|--:|
| chaos ｜ divine | **1 div = 101.75 chaos** | 6,248,398 |
| chaos ｜ exalted | 1 ex ≈ 0.75 chaos（exalted 在 POE1 是廉價通貨） | 40,131 |
| mirror ｜ divine | 1 mirror ≈ 16,614 chaos ≈ 163 div | 14 |

`/Leagues` 給 Allflame 的 `DivinePrice = 101.747`，與 SnapshotPairs 一致。Allflame 的 `IsCurrent = true`。

行情會漂——**引用前重抓，別直接用上面的數字**。實測漂移速度：1 div 從 07-27 的 101.75c 到 07-28 的 120.70c，**一天 +19%**（見 [market.md](market.md)）。跨日沿用等於直接算錯兩成。
