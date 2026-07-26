> ⛔ **POE1 ONLY** — 這個目錄放 POE1 的 API 快照。**不得放入任何 POE2 資料。**

# POE1 reference TSVs — 尚未產生

需要三份，格式比照 `../../poe2/references/`：

| 檔名 | 來源端點 | 欄位 |
|---|---|---|
| `stats.tsv` | `/api/trade/data/stats` | `group<TAB>id<TAB>text`（`#` = 數值佔位符） |
| `items.tsv` | `/api/trade/data/items` | `category<TAB>name<TAB>type<TAB>flags` |
| `static.tsv` | `/api/trade/data/static` | 通貨/碎片 id 表 |

`/api/trade/data/*` 走 Cloudflare，plain curl 會拿到挑戰頁 —— 必須在已開啟的頁面內 fetch：

```bash
playwright-cli --raw eval "(async()=>{const r=await fetch('/api/trade/data/stats');return JSON.stringify(await r.json())})()" > stats_raw.json
# 注意：in-page eval 的輸出是雙層編碼的 JSON 字串 → json.loads() 兩次
```

產生後，在 `../QUERY.md` 的橫幅填上擷取當下的**遊戲版本 / 聯盟 / 日期**。
