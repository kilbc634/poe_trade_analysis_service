> ⛔ **POE1 ONLY** ｜ 聯盟：**Allflame**（遊戲版本未記錄）｜ 最後整理：**2026-07-27**
> 若 `setting.py` 的 `REALM=poe2`，立刻停止並改讀 `../poe2/`。
> **本檔仍在建置中：傳輸層已實測，query schema 與全部遊戲知識還是空的。**
> 下面標 ❓ 的每一項都還沒實測過——不准把 `../poe2/` 的任何 id、欄位名、幣別、機制或行情搬過來填，
> 也不准寫「POE2 是這樣所以 POE1 應該也是」。要嘛實測後寫進來，要嘛照實說不知道。

# POE1 Trade — building search queries

POE1 lives under `/trade/` on the same site as POE2's `/trade2/`. The transport layer (Cloudflare/UA、限流、429 政策、撈池方法、交付格式) is shared and already documented in [`../common/`](../common/) — **read that, it applies here**. What's missing is everything below.

## 建立這份文件的步驟（第一次跑 POE1 時照做）

1. 用 `open-poe-trade` 開站並登入，`setting.py` 設 `REALM=poe1` + 對應的 POE1 聯盟名（例：`Keepers`）。
2. 在頁面內 `fetch` 抓 `/api/trade/data/stats`、`/items`、`/static`、`/filters`，轉成 TSV 放進 `references/`（格式比照 `../poe2/references/`，見 [`references/README.md`](references/README.md)）。`/data/*` 走 Cloudflare，必須 in-page fetch。
3. 在交易頁手動建一個含各類篩選的查詢，按 Search 拿 `query_id`，再 `GET` 回來讀它的完整 `query` JSON——這是取得真實 schema 最快的方法，不要用猜的。
4. 把量到的東西寫進下面各節，把 ❓ 拿掉，並更新檔頭橫幅的版本與日期。

## 已實測（2026-07-27，authenticated）

**端點與 URL —— POE1 路徑裡沒有 realm 區段，也不需要 `?realm=` 參數：**

| 用途 | 路徑 | 備註 |
|---|---|---|
| 搜尋 POST | `/api/trade/search/{league}` | 回 `{id, complexity, result[], total}` |
| 取回已存查詢 | `/api/trade/search/{league}/{query_id}` | 回 `{id, query}` |
| fetch | `/api/trade/fetch/{ids}?query={query_id}` | **一次上限 10 個 hash**；11 個回 `400 {"error":{"code":2,"message":"Invalid query"}}` |
| live websocket | `wss://www.pathofexile.com/api/trade/live/{league}/{query_id}` | 實測 OPEN；加 `/pc/` 的變體 ERROR |

- **搜尋回應存 100 個 result hash**（與 POE2 相同）——深抓價格階梯可用後段。
- **`status.option` 五個值，與 POE2 完全相同**：`securable`（Instant Buyout）/ `available`（Instant Buyout and In Person）/ `onlineleague`（In Person, Online in League）/ `online`（In Person, Online）/ `any`。
- **限流與 POE2 共用同一個池**（實測交錯打兩款遊戲，`trade-search-request-limit` 的 IP 計數連續累加）——詳見 [`../common/tricks.md`](../common/tricks.md)。
- **fetch 回傳結構**（單一樣本 Goldrim，尚未涵蓋所有情況）：`explicitMods` 是物件陣列 `{description, domain, hash, mods:[{magnitudes:[{min,max}]}]}`；`item.extended` 有 `ev`/`ev_aug`/`base_defence_percentile`/`hashes`/`text`；`item.sockets` 存在（POE1 的插槽/連線系統）；`listing.price` 形如 `{type:'~price', amount:1, currency:'chaos'}`；有 `whisper_token`、無 `hideout_token`。
  ❗ 這只是一件普通唯一裝的樣本。**詞綴文字是否像 POE2 那樣內嵌 `[A|B]` wiki 連結、crafted/fractured 等旗標長什麼樣，都還沒驗證**——真的要寫 parser 前先抓幾件稀有裝比對。
- **whisper / 前往藏身處：`POST /api/trade/whisper`**，body `{"token":"<JWT>"}`（token 取自 fetch 回傳的 `listing.whisper_token` / `listing.hideout_token`）。角色**離線時回 `400 "Your account must be in-game to use this feature"`**，不會對賣家送出任何東西；線上時會真的執行。實作範例見 [`script/scavenger.py`](../../../../script/scavenger.py)。

### UI 送出的實際請求（攔截 `window.fetch` / `XHR` 實測）

在 `/trade/search/Allflame/EBO2DX8YS5` 頁面按下 **Search**（`button.btn.search-btn`），攔到兩發請求：

```
XHR POST /api/trade/search/Allflame
GET      /api/trade/fetch/{h1},{h2},{h3}?query=EBO2DX8YS5&pseudos[]=pseudo.pseudo_total_life
```

**確認 UI 打的就是文件記的路徑**，沒有隱藏的 realm 區段或額外參數。條件不變時重按 Search 會沿用同一個 `query_id`，網址不變。

### `pseudos[]` —— fetch 的隱藏參數（UI 會帶，手刻請求容易漏）

fetch 可以重複帶 `&pseudos[]=<pseudo stat id>`，**伺服器就會在回傳裡多給一個 `item.pseudoMods` 陣列，直接算好該 pseudo 的合計值**：

```jsonc
// 帶 pseudos[]=pseudo.pseudo_total_life
"pseudoMods": [ { "description": "+124 total maximum Life", "domain": "pseudo", "hash": "stat.pseudo.pseudo_total_life" } ]
```

不帶就完全沒有這個欄位，得自己從 `explicitMods`/`implicitMods` 逐條加總（還要自己處理混合抗性之類的合併規則）。**凡是用 pseudo 條件搜尋的，fetch 一律把同一組 pseudo id 帶上**，省掉整個加總 parser。（POE2 是否有同樣參數未測，別假設。）

### Live search 不歸這個 skill 管

本 skill 只負責「建查詢、跑搜尋、讀結果」。Live search 已有成熟的實戰實作：**[`script/scavenger.py`](../../../../script/scavenger.py)**（依 `setting.py` 的 `REALM` 自動切換兩款遊戲的 live URL 與 fetch 參數）。需要即時監控時直接用它，不要在這裡另外寫一套或重複記錄它的實作細節。實測確認 POE1 的 live 端點可用（`wss://…/api/trade/live/{league}/{query_id}`，不含 realm 段）。

### 真實 query JSON 樣本（從使用者提供的兩個 query_id 取回）

這是目前僅有的 POE1 schema 實例，補 schema 章節時以此為準：

```jsonc
// EBO2DX8YS5 — 血量 120+ 的獵首
{ "name": "Headhunter", "type": "Leather Belt",
  "stats": [ { "type": "and", "filters": [
      { "id": "pseudo.pseudo_total_life", "value": { "min": 120 }, "disabled": false } ] } ],
  "status": { "option": "securable" } }

// BgOpDMRaH8 — 血量 160+ 的腰帶（第二條是關閉狀態的抗性條件）
{ "stats": [ { "type": "and", "filters": [
      { "id": "pseudo.pseudo_total_life", "value": { "min": 160 } },
      { "id": "pseudo.pseudo_total_elemental_resistance", "value": { "min": 100 }, "disabled": true } ] } ],
  "status": { "option": "securable" },
  "filters": { "type_filters": { "filters": { "category": { "option": "accessory.belt" } } } } }
```

由此確認的片段：`name`+`type` 指定唯一裝、`stats[].type="and"`、`disabled` 旗標、`type_filters.category.option` 存在且腰帶是 `accessory.belt`、pseudo 群組有 `pseudo_total_life` 與 `pseudo_total_elemental_resistance`。**這些只是被這兩個查詢碰到的欄位，不代表 schema 全貌**——其餘仍要從 `lscache-tradefilters` 或更多真實查詢補齊。

## 待驗證清單（每一項都是 ❓）

**Query JSON schema**
- ❓ `filters` 底下有哪些群組。POE2 用 `equipment_filters`，POE1 已知不同（防禦類在別的群組名）——實測確認，不要沿用。
- ❓ POE1 專有的篩選面向：插槽/連線（sockets/links）、影響力（influence）、合成（synthesis）、地下城（delve）、Veiled、Fractured、Scourge…… 這些 POE2 沒有，得逐一從真實 query JSON 讀出來。
- ❓ `status.option` 有哪些值、預設是什麼。
- ❓ `trade_filters.price` 的等值模式基準幣別（POE2 是 exalted；POE1 傳統上是 chaos，**未確認**）。

**Stat ids**
- ❓ 全部。POE1 的 stat hash **一律重新 grep `references/stats.tsv`**。就算某個 hash 看起來跟 POE2 一樣，也不代表語意相同；誤用不會報錯，只會靜默回錯東西。
- ❓ pseudo 群組有哪些（POE1 的 pseudo 池跟 POE2 差很多）。

**類別與基底**
- ❓ `type_filters.category.option` 的完整清單。
- ❓ 唯一裝 / 基底名稱表（`references/items.tsv`）。
- ❓ 通貨 id 表（`references/static.tsv`）。

**匯率**
- ❓ POE1 的行情資料源（poe2scout 是 POE2 專屬，這裡用不了）。找到並驗證後寫進 `knowledge/exchange-rates.md`。

## Knowledge base

`poe1/knowledge/` 目前只有 [INDEX.md](knowledge/INDEX.md) 的空殼。使用者教的每一條 POE1 事實都寫進這裡，並在 INDEX 加一行中英雙語關鍵字。分類原則見 [`../SKILL.md`](../SKILL.md)：**換一款遊戲還成立的才放 `../common/`，其餘全部留在這裡。**
