> ⛔ **POE2 ONLY** — 這個目錄放 POE2 的資料快照。**不得放入任何 POE1 資料。**

# POE2 reference TSVs

**已產出（2026-07-28 重產，聯盟 Runes of Aldur，來源為交易頁 localStorage）：**

| 檔名 | 欄位 | 筆數 |
|---|---|--:|
| `stats.tsv` | `group<TAB>id<TAB>text`（`#` = 數值佔位符） | 8234 |
| `items.tsv` | `category<TAB>name<TAB>type<TAB>flags`（唯一裝有 name 且 flags 為 `FLAG:unique`，基底只有 type） | 3880（含 771 唯一裝） |
| `static.tsv` | `群組<TAB>id<TAB>名稱` | 780 |

`static.tsv` 的群組欄放的是**群組 label**（`Abyssal Bones`、`Uncut Gems`，含空格），與 POE1 那份一致；2026-07-28 之前放的是群組 id（`Abyss`、`UncutGems`），舊 grep pattern 要跟著改。另外裡面有 27 筆 `id == "sep"` 的分隔列（POE1 有 23 筆），是站台資料自帶的 UI 分隔符，查通貨時記得濾掉。

## ⚠ 一列一筆是硬性前提

這些表是逐行 grep 的，所以**一筆資料永遠只能佔一行**。POE2 有 7159 筆詞綴原文含換行（例如 `explicit.stat_1013492127` = `Spells fire # additional Projectiles\nSpells fire Projectiles in a circle`），產檔時一律把換行轉義成字面 `\n`、tab 轉成 `\t`。

**這條規範是補寫的：** 初版 POE2 表沒做轉義，留下 **115 行斷行殘骸**（一筆被拆成多行，尾巴變成只有 1 欄、沒有 id 的孤行），用整段文字 grep 會漏抓。2026-07-28 重產修正。重產完務必跑這兩個 assert：

```bash
awk -F'\t' 'NF!=3' stats.tsv | wc -l   # 必須是 0（items.tsv 用 NF!=4）
# 以及在產檔腳本裡 assert：檔案行數 == 記錄筆數
```

## 取得資料：讀 localStorage（建議）

交易頁載入後會把全部參考資料快取在 localStorage，**不必打任何 API、不耗限流配額、也繞過 Cloudflare**。

> **⚠ POE2 的 key 前綴是 `lscache-trade2*`，POE1 是 `lscache-trade*`。** 同一個 origin 底下**兩套並存**（開過 POE1 交易頁就會有 `lscache-tradestats`），拿錯前綴會安靜地產出另一款遊戲的表。

| localStorage key | 內容 |
|---|---|
| `lscache-trade2stats` | 完整 stat 清單（`[{id, label, entries:[{id, text, type}]}]`） |
| `lscache-trade2items` | 唯一裝／基底（`entries` 有 `name`／`type`／`flags.unique`） |
| `lscache-trade2data` | 通貨等靜態資料 |
| `lscache-trade2filters` | 篩選定義（各下拉的 option 清單） |

每個 key 都有對應的 `<key>-cacheexpiration`（Unix 秒）。用 `open-poe-trade` 開好 POE2 交易頁後：

```bash
playwright-cli --raw eval "localStorage.getItem('lscache-trade2stats')" > stats_raw.json
# 注意：in-page eval 的輸出是雙層編碼的 JSON 字串 → json.loads() 兩次
```

**備援：打 `/api/trade2/data/*` 端點。** 這條走 Cloudflare，plain curl 會拿到挑戰頁，必須在已開啟的頁面內 fetch：

```bash
playwright-cli --raw eval "(async()=>{const r=await fetch('/api/trade2/data/stats');return JSON.stringify(await r.json())})()" > stats_raw.json
```

## 下拉清單不等於 API 接受度

`lscache-trade2filters` 的 category 下拉只有 63 個可選值，但 API 還吃至少一個不在清單上的分類（`wombgift`，2026-07-28 實測 200 且確實有過濾）。**要補完 option 清單，拿 `items.tsv` 的 category 欄去跟下拉取差集，再逐一送 API 試**（無效值回 `400 "Unknown category"`，分得出來）。細節見 [`../QUERY.md`](../QUERY.md)。

產生後，在 [`../QUERY.md`](../QUERY.md) 的檔頭橫幅填上擷取當下的**遊戲版本 / 聯盟 / 日期**。
