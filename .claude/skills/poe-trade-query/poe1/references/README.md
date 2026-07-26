> ⛔ **POE1 ONLY** — 這個目錄放 POE1 的 API 快照。**不得放入任何 POE2 資料。**

# POE1 reference TSVs — 尚未產生

需要三份，格式比照 `../../poe2/references/`：

| 檔名 | 來源端點 | 欄位 |
|---|---|---|
| `stats.tsv` | `/api/trade/data/stats` | `group<TAB>id<TAB>text`（`#` = 數值佔位符） |
| `items.tsv` | `/api/trade/data/items` | `category<TAB>name<TAB>type<TAB>flags` |
| `static.tsv` | `/api/trade/data/static` | 通貨/碎片 id 表 |

## 取得資料的兩條路

**建議：直接讀 localStorage（2026-07-27 發現）。** POE1 交易頁載入後會把全部參考資料快取在 localStorage，**不必打任何 API、不會消耗限流配額、也繞過 Cloudflare**：

| localStorage key | 內容 | 觀測大小 |
|---|---|---|
| `lscache-tradestats` | 完整 stat 清單（`[{id, label, entries:[{id, text, type}]}]`，與 `/data/stats` 同結構） | ~1.98M chars |
| `lscache-tradeitems` | 唯一裝／基底 | ~344K chars |
| `lscache-tradedata` | 通貨等靜態資料 | ~195K chars |
| `lscache-tradefilters` | 篩選定義（含各下拉的 option 清單） | ~17K chars |

每個 key 都有對應的 `<key>-cacheexpiration`（Unix 秒）。用 `open-poe-trade` 開好 POE1 交易頁後：

```bash
playwright-cli --raw eval "localStorage.getItem('lscache-tradestats')" > stats_raw.json
# 注意：in-page eval 的輸出是雙層編碼的 JSON 字串 → json.loads() 兩次
```

`lscache-tradefilters` 特別有用——`query.filters` 底下有哪些群組、每個下拉有哪些 option，全在裡面，是補完 `../QUERY.md` schema 章節最快的來源。

**備援：打 `/api/trade/data/*` 端點。** 這條走 Cloudflare，plain curl 會拿到挑戰頁，必須在已開啟的頁面內 fetch：

```bash
playwright-cli --raw eval "(async()=>{const r=await fetch('/api/trade/data/stats');return JSON.stringify(await r.json())})()" > stats_raw.json
```

產生後，在 `../QUERY.md` 的橫幅填上擷取當下的**遊戲版本 / 聯盟 / 日期**。
