> ⛔ **POE1 ONLY** ｜ 遊戲版本：**尚未建立** ｜ 最後整理：**—**
> 若 `setting.py` 的 `REALM=poe2`，立刻停止並改讀 `../poe2/`。
> **本檔目前是空殼。** 下面標 ❓ 的每一項都還沒實測過——不准把 `../poe2/` 的任何 id、欄位名、幣別、機制或行情搬過來填，
> 也不准寫「POE2 是這樣所以 POE1 應該也是」。要嘛實測後寫進來，要嘛照實說不知道。

# POE1 Trade — building search queries

POE1 lives under `/trade/` on the same site as POE2's `/trade2/`. The transport layer (Cloudflare/UA、限流、429 政策、撈池方法、交付格式) is shared and already documented in [`../common/`](../common/) — **read that, it applies here**. What's missing is everything below.

## 建立這份文件的步驟（第一次跑 POE1 時照做）

1. 用 `open-poe-trade` 開站並登入，`setting.py` 設 `REALM=poe1` + 對應的 POE1 聯盟名（例：`Keepers`）。
2. 在頁面內 `fetch` 抓 `/api/trade/data/stats`、`/items`、`/static`、`/filters`，轉成 TSV 放進 `references/`（格式比照 `../poe2/references/`，見 [`references/README.md`](references/README.md)）。`/data/*` 走 Cloudflare，必須 in-page fetch。
3. 在交易頁手動建一個含各類篩選的查詢，按 Search 拿 `query_id`，再 `GET` 回來讀它的完整 `query` JSON——這是取得真實 schema 最快的方法，不要用猜的。
4. 把量到的東西寫進下面各節，把 ❓ 拿掉，並更新檔頭橫幅的版本與日期。

## 待驗證清單（每一項都是 ❓）

**端點與 URL**
- ❓ 搜尋 POST 路徑：預期 `/api/trade/search/{league}`，但**是否帶 realm 區段或 `?realm=` 參數尚未確認**。注意 POE1 的 `realm` 歷史上指的是平台（`pc`/`xbox`/`sony`），跟 POE2 URL 裡那個 `poe2` 區段不是同一個概念——不要混為一談。
- ❓ fetch 路徑與每次可帶的 hash 上限（POE2 是 10，POE1 未測）。
- ❓ 搜尋回應存幾個 result hash（POE2 是 100，POE1 未測）——深抓價格階梯要用到。
- ❓ 交易頁 URL 形式與 `query_id` 的取法。
- ❓ localStorage 狀態 key：`open-poe-trade` 記的是 `lscache-tradestate`，實跑時確認一次。

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
