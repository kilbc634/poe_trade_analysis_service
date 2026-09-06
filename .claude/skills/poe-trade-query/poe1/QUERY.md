> ⛔ **POE1 ONLY** ｜ 聯盟：**Allflame**（3.29 Curse of the Allflame）｜ 最後整理：**2026-08-17**
> 若 `setting.py` 的 `REALM=poe2`，立刻停止並改讀 `../poe2/`。
> **狀態：傳輸層與 query schema 已實測可用；`knowledge/` 已有匯率、腰帶部位分佈與腰帶行情，其餘部位與機制估值待累積。**
> 下面標 ❓ 的每一項都還沒實測過——不准把 `../poe2/` 的任何 id、欄位名、幣別、機制或行情搬過來填，
> 也不准寫「POE2 是這樣所以 POE1 應該也是」。要嘛實測後寫進來，要嘛照實說不知道。

# POE1 Trade — building search queries

POE1 lives under `/trade/` on the same site as POE2's `/trade2/`. The transport layer (Cloudflare/UA、限流、429 政策、撈池方法、交付格式) is shared and already documented in [`../common/`](../common/) — **read that, it applies here**. What's missing is everything below.

## 建立這份文件的步驟（第一次跑 POE1 時照做）

1. 用 `open-poe-trade` 開站並登入，`setting.py` 設 `REALM=poe1` + 對應的 POE1 聯盟名（目前是 `Allflame`，以 `setting.py` 的 `LEAGUE` 為準）。
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

- **給使用者點的結果頁 URL：`https://www.pathofexile.com/trade/search/{league}/{query_id}`**（實測所見，見下方 UI 攔截那節的 `/trade/search/Allflame/EBO2DX8YS5`）。聯盟名要 URL-encode。`../common/tricks.md` 的預設交付規則是「只給連結、不要 `goto` 過去」，連結就照這個格式組。
- ⭐ **結果頁網址有兩種形式，長的那種不是 query_id**（2026-09-05 實測）：
  - 短的（例 `EBO2DX8YS5`）是**存下來的查詢**，可以 `GET /api/trade/search/{league}/{id}` 取回。
  - 長的（`H4sIAAAA…`，數百字元）是**把整個 query 用 gzip 壓縮再 base64url 編碼塞進網址**。
    拿它去 GET 會回 **404 `{"error":{"code":1,"message":"Resource not found"}}`**——
    它從來沒被存到伺服器上。**要在本地解**：
    ```python
    import base64, gzip, json
    q = json.loads(gzip.decompress(base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))))
    ```
    解出來就是完整的 query JSON，可以直接 POST 到 `/api/trade/search/{league}` 重跑。
    使用者貼這種連結過來時就用這條路，不要先試 GET。
- **搜尋回應存 100 個 result hash**（與 POE2 相同）——深抓價格階梯可用後段。
- **`status.option` 五個值，與 POE2 完全相同**：`securable`（Instant Buyout）/ `available`（Instant Buyout and In Person）/ `onlineleague`（In Person, Online in League）/ `online`（In Person, Online）/ `any`。
- **限流與 POE2 共用同一個池**（實測交錯打兩款遊戲，`trade-search-request-limit` 的 IP 計數連續累加）——詳見 [`../common/tricks.md`](../common/tricks.md)。
- **fetch 回傳結構**：`item.extended` 有 `ev`/`ar`/`es`/`ev_aug`/`base_defence_percentile`/`hashes`/`text`；`item.sockets` 存在（POE1 的插槽/連線系統）；`listing.price` 形如 `{type:'~b/o', amount:7, currency:'chaos'}`；有 `whisper_token` **或** `hideout_token`（二擇一，見下方 whisper 那節）；稀有裝另有 `note`（賣家標價註記）、`requirements`、`properties`。

### 詞綴回傳格式（稀有鞋實測，含 crafted）

**每條詞綴都是物件，不是字串**（至少稀有裝如此），且**工藝詞綴混在 `explicitMods` 裡，沒有獨立的 `craftedMods` 陣列**：

```jsonc
// 一般詞綴
{ "description": "+128 to maximum Life", "domain": "explicit",
  "hash": "stat.explicit.stat_3299347043",
  "mods": [ { "name": "Athlete's", "tier": "P1", "level": 54,
              "magnitudes": [ { "min": "115", "max": "129" } ] } ] }

// 工藝詞綴 —— 三個地方都標得出來
{ "description": "+31% to Fire Resistance",
  "flags": { "crafted": true },              // ← 旗標
  "domain": "crafted",                       // ← domain 也是 crafted
  "hash": "stat.crafted.stat_3372524247",    // ← hash 走 crafted 命名空間
  "mods": [ { "name": "of Craft", "tier": "R3", "level": 50,
              "magnitudes": [ { "min": "29", "max": "35" } ] } ] }
```

要點：
- 判斷工藝詞綴看 `flags.crafted` 或 `domain=="crafted"` 皆可；**別去找 `craftedMods` 欄位，它不存在**。
- `hash` 一律是 `stat.<group>.<id>` —— 比查詢時用的 id（`crafted.stat_3372524247`）多一個 `stat.` 前綴，比對前要去掉。
- 每條都自帶 `mods[].tier` 與 `magnitudes` 的 roll 區間，可直接判斷這條是不是接近該階上限，不必另外查表。
### ⭐ 一條詞綴可以渲染成多行／多條 stat —— 分組鍵是 `mods[].(name, tier)`（2026-09-05 實測）

這是解析 POE1 詞綴最容易靜靜算錯的地方，而且**交易站其實有給我們分組資訊**，只是不在明顯的位置。

> **先講結論（使用者 2026-09-05 指正的重點）**：這些形狀**對數值加總幾乎沒影響**——
> 複合詞綴的每個 stat 各自生效，合併顯示的數字也是正確總量。
> **真正會踩坑的是「還有沒有空前綴／空後綴」的判斷**，也就是能不能再上一條工藝詞綴。
> 那個判斷必須**精準數詞綴數量**，而顯示行數不等於詞綴數量——
> 作法與實測見 [knowledge/crafting.md](knowledge/crafting.md) 的「備援：從 fetch 回傳自己判斷後綴空位」。

**三種形狀，不要混為一談——其中只有 A 和 C 在現行遊戲裡存在：**

| 形狀 | 長相 | 怎麼判 | 正確處理 |
|---|---|---|---|
| **A 換行斷句** | 一條 stat 的句子被折行，第二行是句子的後半 | `description` 內含字面 `\n` | **合成一行判斷條件**。拆開的話後半段會被當成常駐效果 |
| ~~**B 一條 stat 綁兩個獨立效果**~~ | `+7% to Chaos Resistance` ＋ `Minions deal …` 同一個 `description`<br>⛔ **這形狀在現行遊戲裡不存在**：唯一的實例是 `crucible.mod_28602`，而 **Crucible 已從遊戲移除**（使用者 2026-09-05）| — | **不必處理** |
| **C 一條詞綴 = 多條 stat** | 神廟手套：暴擊/傷害一行、抗性一行 | **兩個獨立的 `description`，`mods[].(name, tier)` 相同** | 靠 `(name, tier)` 分組，**與換行無關** |

**C 的實測證據**（一隻 Wyrmscale Gauntlets）：

```jsonc
{ "description": "+46% to Lightning Resistance",
  "hash": "stat.explicit.stat_1671376347",
  "mods": [ { "name": "of Puhuarte", "tier": "S0" } ] }
{ "description": "54% increased Critical Strike Chance against Shocked Enemies",
  "hash": "stat.explicit.stat_276103140",
  "mods": [ { "name": "of Puhuarte", "tier": "S0" } ] }   // ← 同一條詞綴
```

同一件上 `29% increased Armour and Evasion` 與 `13% increased Stun and Block Recovery`
也共用 `("Rhino's", "P3")`。所以 **`mods[].(name, tier)` 就是「一次 roll 給了什麼」的單位**，
[knowledge/crafting.md](knowledge/crafting.md) 數空後綴時說的「要數不重複的 `(name, tier)`」用的是同一把鑰匙。

**規模（掃完 `references/stats.tsv` 全部 17325 列，2026-09-05）：**

含字面 `\n` 的共 **2025** 列，但其中 **1682 列是 `crucible`**——**那個機制已經從遊戲移除**
（見下方「已死的 stat 群組」），所以**現行遊戲裡只有 343 列**，而且全部落在會出現在
可交易裝備上的 group：`explicit 286`／`fractured 27`／`implicit 17`／`enchant 7`／
`scourge 3`／`delve 2`／`crafted 1`。

這 343 列裡：

- **只有 1 列**碰到「抗性／生命／屬性」的評分正則：
  `explicit.stat_3403551644` = `Inflict Fire Exposure on Hit against Enemies with\n5 Cinderflame, applying #% to Fire Resistance`
  ——形狀 A（條件在第一行、數字在第二行）。
- 第二行像「新的一句」的有 **56 列**，逐筆看過，**0 列**帶扁平生命／抗性／屬性。

**所以在現行遊戲裡，「換行」只會是形狀 A，不存在需要逐行判條件的反例。**

**由此得到的解析規則**（實作見
[`../scripts/gear_combo_res4_poe1.py`](../scripts/gear_combo_res4_poe1.py) 的 `_scan_mods`）：

> **條件守衛判「整個 description（換行接起來）」，數值評分「逐行」。**

理由就是上面那組數字：**形狀 A 是唯一會碰到評分的換行情形，而形狀 B 沒有活著的實例**，
所以這條規則不是取捨、是直接正確的。

反過來「一律逐行判條件」會漏掉 A 的條件、**高估抗性**——那是會交出「看起來達標其實破防」的方向。
（這個坑我自己踩過：先寫成逐行判，直到使用者質疑「裝備上應該沒有這種複合詞綴」才回頭查，
發現支撐逐行判的那個例子出自已移除的機制。）

⚠ **不要試著用啟發式去分辨 A 和 B**。那 56 筆的「第二行像不像新句子」分類器只是
**做那次稽核用的**，不該進解析流程——既然 B 不存在，就沒有要分辨的東西。

那 56 筆的實際內容供參考（都與評分無關）：**藥劑的雙免疫**
（`Grants Immunity to Chill …` ＋ `Grants Immunity to Freeze …`）、
**地圖裝置的 `Players have …` 重複行**、**多行的觸發／循環敘述**
（`Every 5 seconds, gain one of the following …`）。

⚠ **`grep '\n' stats.tsv` 會給你假數字**：BRE 把 `\n` 當成字母 `n`，會 match 到幾乎每一列
（實測回 15983／17325）。要數字面反斜線加 n **必須用 `grep -F`**。

- `extended.mods` 在這件樣本是**空的**（`{}`）——階級資訊在各詞綴物件裡，不在 extended 底下。
- **描述文字是純文字，沒有內嵌 wiki 連結括號**（`+31% to Fire Resistance`、`+128 to maximum Life`）。這件樣本的 5 條詞綴都沒有；若之後遇到含括號的再補記。
- **whisper / 前往藏身處：`POST /api/trade/whisper`**，body `{"token":"<JWT>"}`。角色**離線時回 `400 "Your account must be in-game to use this feature"`**，不會對賣家送出任何東西；線上時會真的執行（實測回 `{"success":true}`，約 1.9 秒）。實作範例見 [`script/wholesalers.py`](../../../../script/wholesalers.py)。
- **POE1 的 token 分兩種，同一筆掛單只會有其中一種**，決定於**該掛單是不是 Instant Buyout（離線交易）**，不是倉庫頁種類（2026-08 實測 71 筆）：
  - **`hideout_token`**（JWT `tok:"hideout"`）：Instant Buyout 掛單，也就是 `status.option = "securable"` 搜得到的那些。送出後**直接把你傳送到賣家藏身處自助購買**，賣家 `account.online` 為 `null`（離線）照樣成立 —— 這就是「離線交易」。這類掛單另有 `fee` 欄位（6c 的 T16 地圖 fee=810）。JWT 效期 300 秒（`exp - iat`），但正常流程 fetch 完馬上就送出，碰不到。
  - **`whisper_token`**：非 Instant Buyout 的舊式掛單。這支只是**發密語給賣家**，不會傳送，所以沒有自動購買的觸發點。**使用者說明（2026-08）：自從 Instant Buyout 上線後，實務上已經沒有玩家在用舊的密語模式了**，所以自動化腳本只要把查詢設成 `securable`，就可以當作 `hideout_token` 必定存在（`listing["hideout_token"]` 直接取值即可）。
  - POE2 則一律是 `hideout_token`（且沒有 `whisper_token`）。
- **Instant Buyout 掛單的倉庫座標一定落在 12×12 一般倉庫頁內**（實測 40 筆 securable 掛單，`stash.x`/`stash.y` 最大值都是 11，零例外）—— 四倍頁那類版面不支援 Instant Buyout，所以自動點格的腳本不必為它們做特例。反之若查詢沒設 securable，撈到的一般掛單就會出現 `(182,0)`、`(16,20)` 這種命運卡片頁/四倍頁座標。

### UI 送出的實際請求（攔截 `window.fetch` / `XHR` 實測）

在 `/trade/search/Allflame/EBO2DX8YS5` 頁面按下 **Search**（`button.btn.search-btn`），攔到兩發請求：

```
XHR POST /api/trade/search/Allflame
GET      /api/trade/fetch/{h1},{h2},{h3}?query=EBO2DX8YS5&pseudos[]=pseudo.pseudo_total_life
```

**確認 UI 打的就是文件記的路徑**，沒有隱藏的 realm 區段或額外參數。條件不變時重按 Search 會沿用同一個 `query_id`，網址不變。

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

## Query JSON schema

來源：`lscache-tradefilters`（交易頁自己的篩選定義，2026-07-27 dump）+ 上面兩個真實查詢。欄位名與 option id 都是站台原始值，不是推的。

```jsonc
{
  "query": {
    "status": { "option": "securable" },   // 在 query 根層，不在 filters 裡
    "term":  "free text",                  // 純文字搜尋
    "name":  "Headhunter",                 // 唯一裝名（精確）
    "type":  "Leather Belt",               // 基底名（精確）
    "stats": [ { "type": "and", "filters": [
        { "id": "pseudo.pseudo_total_life", "value": { "min": 120 }, "disabled": false } ] } ],
    "filters": {
      "type_filters":     { "filters": { "category": {"option":"accessory.belt"}, "rarity": {"option":"unique"} } },
      "weapon_filters":   { "filters": { "dps": {"min":400} } },
      "armour_filters":   { "filters": { "es": {"min":300} } },
      "socket_filters":   { "filters": { "links": {"min":6} } },
      "req_filters":      { "filters": { "lvl": {"max":90} } },
      "map_filters":      { "filters": { "map_tier": {"min":16} } },
      "heist_filters":    { "filters": { "heist_lockpicking": {"min":3} } },
      "sanctum_filters":  { "filters": { "sanctum_resolve": {"min":100} } },
      "ultimatum_filters":{ "filters": { "ultimatum_challenge": {"option":"Exterminate"} } },
      "misc_filters":     { "filters": { "corrupted": {"option":"false"}, "ilvl": {"min":86} } },
      "trade_filters":    { "filters": { "price": {"option":"chaos","max":50}, "indexed": {"option":"1day"} } }
    }
  },
  "sort": { "price": "asc" }
}
```

值的形狀：min/max 欄位吃 `{"min":N}` / `{"max":N}` / 兩者；下拉吃 `{"option":"<id>"}`；布林是字串 `"true"`/`"false"`；要「不限」就整個欄位省略（站台把 `None` 當未選，不要真的送 `"None"`）。

**已實跑驗證**（2026-07-27）：同時使用 `type_filters` + `armour_filters.es` + `socket_filters.links` + `req_filters.lvl` + `misc_filters`(corrupted/ilvl) + `trade_filters`(price option=chaos / indexed) + pseudo stat 條件的查詢回 `200`，`total=50`。上表的群組名與欄位名可直接使用。

### 篩選群組與欄位（完整 12 組）

| 群組 | 欄位 |
|---|---|
| `status_filters` | 只有 `status`，但實際查詢裡它放在 **query 根層**而非此群組下 |
| `type_filters` | `category`(opt)、`rarity`(opt) |
| `weapon_filters` | `damage`、`aps`、`crit`、`dps`、`pdps`、`edps` |
| `armour_filters` | `ar`、`ev`、`es`、`ward`、`block`、`base_defence_percentile` |
| `socket_filters` | `sockets`、`links` —— **兩者除了 `min`/`max` 還吃顏色子欄位 `r`/`g`/`b`/`w`**（2026-08-17 實測） |
| `req_filters` | `lvl`、`str`、`dex`、`int`、`class`(opt) |
| `map_filters` | `map_tier`、`map_packsize`、`map_iiq`、`map_iir`、`map_gold`、`chart_sulphur`、`chart_shape`(opt)、`area_level`、`map_series`(opt, 28)、`map_blighted`(opt)、`map_uberblighted`(opt)、`map_completion_reward`(opt) |
| `heist_filters` | `heist_wings`/`heist_max_wings`、`heist_escape_routes`/`_max_`、`heist_reward_rooms`/`_max_`、`heist_objective_value`(opt)、以及八種技能等級 `heist_lockpicking`/`_brute_force`/`_perception`/`_demolition`/`_counter_thaumaturgy`/`_trap_disarmament`/`_agility`/`_deception`/`_engineering` |
| `sanctum_filters` | `sanctum_resolve`、`sanctum_max_resolve`、`sanctum_inspiration`、`sanctum_gold`(Aureus) |
| `ultimatum_filters` | `ultimatum_challenge`(opt)、`ultimatum_reward`(opt)、`ultimatum_input`(opt)、`ultimatum_output`(opt) |
| `misc_filters` | min/max：`quality`、`ilvl`、`gem_level`、`gem_level_progress`、`memory_level`、`stored_experience`、`stack_size`、`scourge_tier`；true/false：`identified`、`corrupted`、`mirrored`、`split`、`crafted`、`veiled`、`foreseeing`、`vestigial`、`fractured_item`、`synthesised_item`、`searing_item`(Searing Exarch)、`tangled_item`(Eater of Worlds)、`gem_transfigured`、`gem_vaal`、`gem_imbued`、`alternate_art`、`crucible_item`、`mutated`(Foulborn)；其他 opt：`foil_variation`(17)、`corpse_type`(7) |
| `trade_filters` | `account`、`collapse`(opt)、`indexed`(opt)、`sale_type`(opt)、`fee`、`price`(opt+min/max) |

### 主要 option 清單

- **`rarity`**：`normal` `magic` `rare` `unique` `uniquefoil` `nonunique`
- **`req_filters.class`**：`scion` `marauder` `ranger` `witch` `duelist` `templar` `shadow`
- **`indexed`**：`1hour` `3hours` `12hours` `1day` `3days` `1week` `2weeks` `1month` `2months`
- **`sale_type`**：`any` `priced_with_info` `unpriced`
- **`price.option`（下拉共 18 項，其中 1 項是未選 → **可送出的幣別是 17 種**；2026-07-28 重 dump 核對無誤）**：`chaos_divine`（＝「Chaos or Divine Orbs」，兩種都算）`chaos` `exalted` `divine` `mirror` `blessed` `chrome` `gcp` `jewellers` `scour` `regret` `fusing` `chance` `alt` `alch` `regal` `vaal`
  - **省略 `option` 時的等值基準幣別是 chaos。** UI 該下拉的未選狀態直接標示 **"Chaos Orb Equivalent"**；poe2scout 的 POE1 聯盟資料也回 `BaseCurrencyApiId: "chaos"`，兩邊一致。換算用的是 GGG 內部匯率、會偏離市場行情——用法與陷阱見 [`../common/tricks.md`](../common/tricks.md)。
- **`trade_filters.account`（賣家過濾，2026-07-28 實測）**：值形狀 **`{"input": "帳號名#1234"}`**。
  - **帳號名必須帶 `#1234` 尾碼**——實測 `{"input":"Murrstaar#4661"}` 回 `total=4`，同一組條件只寫 `{"input":"Murrstaar"}` 回 **`total=0`**（不報錯，靜靜地什麼都撈不到）。`listing.account.name` 回來就已經含尾碼，直接原樣塞回去即可。
  - 送純字串（`"account": "Murrstaar#4661"`）伺服器也吃，而且**正規化成同一筆查詢**（兩者回同一個 `query_id`；GET 回來看到的是 `{"input": …}`）。以 `{"input": …}` 為準寫。
  - 這正是 [`../common/delivery.md`](../common/delivery.md) 交付標準要的「賣家過濾連結」；連結格式見上面端點那節。
- **`heist_objective_value`**：`moderate` `high` `precious` `priceless`
- **`ultimatum_challenge`**：`Exterminate` `Survival` `Defense` `Conquer`｜**`ultimatum_reward`**：`DoubleCurrency` `DoubleDivCards` `MirrorRare` `ExchangeUnique`
- **`corpse_type`**：`eldritch` `demon` `construct` `undead` `beast` `humanoid`

### `type_filters.category.option`（下拉共 83 項，含 1 項未選 → **可送出的分類 82 個**，全列於下；2026-07-28 重 dump 逐項核對無誤）

> ⚠ 本檔所有 option 計數都沿用站台下拉的長度，**含開頭那個 `None`（未選＝Any）**。要「不限」就整個欄位省略，不要送 `"None"`。

武器：`weapon` `weapon.one` `.onemelee` `.twomelee` `.bow` `.claw` `.dagger` `.basedagger` `.runedagger` `.oneaxe` `.onesword` `.basesword` `.rapier` `.onemace` `.basemace` `.sceptre` `.staff` `.basestaff` `.warstaff` `.twoaxe` `.twomace` `.twosword` `.wand` `.rod`
防具：`armour` `armour.chest` `.boots` `.gloves` `.helmet` `.shield` `.quiver`
飾品：`accessory` `accessory.amulet` `.belt` `.ring` `.trinket`
寶石／珠寶：`gem` `gem.activegem` `.supportgem` `.supportgemplus`｜`jewel` `jewel.base` `.abyss` `.cluster`
地圖與內容：`flask`、`map` `map.fragment` `.breachstone` `.invitation` `.scarab`、`leaguestone`、`memoryline`、`card`、`chart`、`logbook`
怪物／異界：`monster.beast` `.yellowbeast` `.redbeast`、`corpse`、`idol`、`graft`、`wombgift`、`enshrouded`、`tincture`
搶劫：`heistequipment` `.heistweapon` `.heisttool` `.heistutility` `.heistreward`、`heistmission` `.contract` `.blueprint`
聖域：`sanctum.research` `sanctum.relic`
通貨：`currency` `currency.piece` `.resonator` `.fossil` `.incubator` `.heistobjective` `.omen` `.tattoo`

## Stat ids

格式 `<group>.stat_<hash>`（pseudo 例外，用具名 id 如 `pseudo.pseudo_total_life`）。**14 個群組**，同一段詞綴文字在不同群組是不同 id：

### ⚠ 配裝時要排除的兩個群組——**但理由完全不同，不要混為一談**

（使用者 2026-09-05 逐一確認）

| 群組 | 條目 | 狀態 | 配裝時 | 其他用途 |
|---|--:|---|---|---|
| `crucible` | 2492 | ⛔ **機制已從遊戲移除很久** | 排除 | **沒有**。整批死資料 |
| `mercenary` | 534 | ✅ **機制還在** | 排除 | **有**：它是「**傭兵物品**」（傭兵契約那類）的篩選用詞綴，與裝備詞綴是**完全不同的東西** |

- **`crucible` 是死的**：不要拿它的條目做統計、不要照它的形狀設計解析、也不要花時間驗它的群組結構。
  `stats.tsv` 還留著它只是因為交易站的篩選定義沒清乾淨；`stats[].type` 的
  `crucible`（Crucible Passive Tree Path）與 `misc_filters.crucible_item` 同理，都是遺留欄位。
- **`mercenary` 是活的，只是不屬於裝備這個領域**。所以**不可以**把它當成死資料——
  它就是傭兵物品查價會用到的那一批。**「配裝時無視」≠「這個群組沒用」**，
  寫工具時別把它一起黑名單掉。
  （本專案另有查傭兵契約價的用途，見 `script/` 那邊；把 mercenary 當死資料會直接害到它。）

⚠ **這會影響統計**：報「全表有幾筆」之前，先想清楚問的是哪個領域。

- 問「裝備詞綴的規模」→ 要扣掉 `crucible`（死）**與** `mercenary`（別的領域）：
  17325 − 2492 − 534 = **14299**。
- 只扣死資料 → 17325 − 2492 = 14833。
- 不扣 → 17325，而這個數字曾經讓本檔上面那個換行統計被 1682 筆死資料**放大 6 倍**
  （2025 vs 實際 343）。順帶一提那 343 筆裡 **`mercenary` 是 0 筆**，
  所以換行這件事本來就與傭兵無關。

| group | 條目數 | | group | 條目數 |
|---|--:|---|---|--:|
| `explicit` | 7433 | | `crucible` | 2492 |
| `enchant` | 2035 | | `fractured` | 1810 |
| `implicit` | 1460 | | `mercenary` | 534 |
| `scourge` | 409 | | `pseudo` | 298 |
| `crafted` | 288 | | `sanctum` | 240 |
| `imbued` | 162 | | `delve` | 81 |
| `ultimatum` | 63 | | `veiled` | 20 |

**查法：** grep `references/stats.tsv`（欄位 `group<TAB>id<TAB>text`，`#` 是數值佔位符）。

```bash
grep -i "maximum life" references/stats.tsv | grep -E "^(pseudo|explicit)"
```

⚠ 有 2025 筆詞綴原文含換行，TSV 裡轉義成字面 `\n` 以維持「一列一筆」。比對整段文字時記得處理。
**但其中 1682 筆是已移除的 `crucible`，存活的只有 343 筆**（`mercenary` 0 筆）——
怎麼正確處理換行見上面「一條詞綴可以渲染成多行／多條 stat」那節。

### Stat 群組類型（`stats[].type`）— 八種

取自交易頁 `+ Add Stat Group` 元件自身的資料（`multiselect.__vue__.options`），不是猜的：

| `type` | UI 名稱 | 群組有 min/max | 條目有 weight |
|---|---|:--:|:--:|
| `and` | And | | |
| `not` | Not | | |
| `if` | If | | |
| `count` | Count | ✓ | |
| `weight` | Weighted Sum | ✓ | ✓ |
| `weight2` | Weighted Sum v2 | ✓ | ✓ |
| `crucible` | Crucible Passive Tree Path | | |
| `mercenary` | Mercenary Skill Group | | |

語義（元件內附的說明）：`if` = 該詞綴存在時才套用 min/max；`count` = 數有幾條符合，再用群組的 min/max 篩數量；`weight`/`weight2` = 各條 stat 值乘上 `weight` 後加總，用群組 min/max 篩總和。

群組本身也吃 `"disabled": true`（整組停用），單一條目同樣可以 `disabled`。

✅ **`socket_filters` 的顏色子欄位實測可用（2026-08-17）**：

```jsonc
"socket_filters": { "filters": {
    "links":   { "min": 6 },
    "sockets": { "b": 2, "r": 2 }   // 語義是「至少 N 個該色」，多個顏色之間是 AND
} }
```

實測 28 筆回傳全部符合 `B≥2 且 R≥2`。`r`/`g`/`b`/`w` 四色皆可，可與 `min`/`max` 並用。
實例（君主之膚挑插槽顏色）見 [knowledge/releveling.md](knowledge/releveling.md)。

✅ **`not` 群組實測可用（2026-08-17）**：`{"type":"not","filters":[{"id":…}, …]}` 一組可放多條，
語義是「這些詞綴一條都不能有」。實例：君主之膚排除 16 個不能用的核心天賦，
在架 3116 → 1982（15 條版本量測），抽驗確認無漏網（見 [knowledge/releveling.md](knowledge/releveling.md)）。
**核心天賦在 `stats.tsv` 裡就是以天賦英文名為文字的 explicit 詞綴**（例：`explicit.stat_2648570028` = `Ancestral Bond`）。

✅ **`pseudo.pseudo_has_shaper_influence` 實測可用，而且要**不帶 value**送（2026-09-05）**：
`{"id": "pseudo.pseudo_has_shaper_influence", "disabled": false}`，不要給 `value.min`。
驗證方式是同一組條件加減這一條看 `total` 變化：鞋子 120 → **67**、
戒指（未腐化未鏡像＋有空前綴）生命≥90 從 10000+ → **1080**、三抗≥90 從 10000+ → **451**。
影響力（Shaper/Elder/…）**不在 `misc_filters` 的 18 個布林裡**，只能走 pseudo。

⚠ **`#% increased Cooldown Recovery Rate` 在 `stats.tsv` 有兩個同文字的 id，只有一個是裝備詞綴**
（2026-09-05 實測，同一組鞋子條件各送一次）：

| id | 同條件在架數 |
|---|--:|
| `explicit.stat_1004011302` | **67** ← 這個才是裝備上的 |
| `explicit.stat_239144` | **0** |

`grep` 出多個同文字 id 時**不要挑一個就用**——把每個單獨送一次看 `total`，0 的那個就是別的東西
（地圖詞綴／光環之類）。不確定就包成 `count` 群組當 OR，兩邊都涵蓋。

✅ **`count` 群組實測可用（2026-07-28）**：`{"type":"count","value":{"min":1},"filters":[…]}` 回 200，可用來表達「下列條件至少滿足 N 條」的 OR 語義。實例（找可上工藝抗性的裝備）見 [knowledge/crafting.md](knowledge/crafting.md)。

✅ **`weight` 群組實測可用（2026-08-17，推翻本檔 07-28 的紀錄）**——關鍵是**權重要放在條目的 `value.weight` 裡**，不是條目或群組的頂層欄位：

```jsonc
"stats": [
  { "type": "and", "filters": [] },                    // ← UI 一定會帶一個空的 and 群組
  { "type": "weight", "value": { "min": 77 },          // ← 門檻放群組的 value.min
    "filters": [
      { "id": "explicit.stat_1573130764", "value": { "weight": 1 } },
      { "id": "explicit.stat_4067062424", "value": { "weight": 1 } },
      { "id": "explicit.stat_1754445556", "value": { "weight": 1 } }
    ] }
]
```

- **計分方式：每條詞綴取其數值區間的中點（`(min+max)/2`）× 權重，全部加總**，再用群組的 `value.min` 篩。
  驗證：`min=77` 回來的物品，三條「Adds X to Y … Damage to Attacks」算出的 Σ(lo+hi)/2 正好是 77。
- 因此 **`weight` 可以表達「這些詞綴我都要，但只在乎總量」**——這是 `and`（逐條下限）與 `count`（只數條數）都做不到的語義。
- **07-28 那次記成「一送就撞複雜度上限」，原因幾乎確定是權重欄位的形狀寫錯**（放在條目頂層而非 `value` 內）。
  型別名本身早就驗證有效（送假值 `xyzzy` 回 `Invalid statgroup type type`，與複雜度錯誤不同）。
  **教訓：拿不到預期回應時，先去 UI 建一個同型查詢、用 `GET /api/trade/search/{league}/{query_id}` 取回原文比對，
  不要直接把失敗歸因到伺服器限制。** 這次就是使用者提供 query_id 才發現的。
- 實例（重練套裝挑附加點傷）見 [knowledge/releveling.md](knowledge/releveling.md)。`weight2` 尚未實測。

## 參考表（`references/`，2026-07-27 產出）

從交易頁 localStorage 快取產生，非 API 直取——作法見 [`references/README.md`](references/README.md)。

| 檔案 | 內容 | 筆數 |
|---|---|--:|
| `stats.tsv` | `group<TAB>id<TAB>text` | 17325 |
| `items.tsv` | `category<TAB>name<TAB>type<TAB>flags`（唯一裝有 name，基底只有 type） | 5997（含 1544 唯一裝） |
| `static.tsv` | `群組<TAB>id<TAB>名稱`（通貨、碎片、精華等） | 1433 |

## 待驗證清單（每一項都是 ❓）

> **優先度低（使用者 2026-07-27 判定）** —— 這幾項實務上很少用到，**不要主動花時間去補**。等真的碰到需求時再照下面的線索驗一次就好。

- ❓ **`weight2` 的語義與 `weight` 差在哪**（`weight` 本身已於 2026-08-17 實測可用，見上）。
- ~~❓ **`crucible`** 群組的條目結構~~ → **結案：不驗。機制已移除**（使用者 2026-09-05），群組整批作廢，見上面「已死的群組」。
- ~~❓ **`mercenary`** 群組的條目結構~~ → **配裝這條線結案：機制還在，但它是「傭兵物品」的篩選詞綴，與裝備詞綴無關，配裝一律無視**（使用者 2026-09-05）。**真的要查傭兵物品本身時再驗**，那時它就不是可以跳過的東西了——別把它當成死群組。
- ❓ **fractured / synthesised / scourge / veiled 等其他旗標的回傳長相**。crafted 已確認（見上），其餘照同樣方法抓一件比對即可。

*（2026-07-28 已結案：`trade_filters.account` 的值形狀、`price.option` 與 `category.option` 的完整清單、結果頁 URL 格式，全部實測完畢並寫進上面各節。）*

## 配裝工具（多部位聯合求解）

**先照需求挑對腳本**——三支都是 POE1，差別在目標函數、約束軸數與部位結構：

| 需求 | 用哪支 |
|---|---|
| 目標只有**生命**、約束只有**三抗** | [`gear_combo_optimizer_poe1.py`](../scripts/gear_combo_optimizer_poe1.py) |
| 目標是**生命＋ES 加權**、還要顧**力量／敏捷**等屬性 | [`gear_combo_es_poe1.py`](../scripts/gear_combo_es_poe1.py) |
| 約束含**混沌抗**、或**同一類別要買兩件**（雙戒）、或每個部位各有自己的硬條件 | [`gear_combo_res4_poe1.py`](../scripts/gear_combo_res4_poe1.py) |

**[`../scripts/gear_combo_optimizer_poe1.py`](../scripts/gear_combo_optimizer_poe1.py)** —— POE1 專用，
2026-07-28 以「30c 配齊六部位補血補抗」實戰驗證過。子命令：
`selftest`（對拍驗算，改求解器後必跑）／`probe`／`pools`／`solve`／`verify`／`converge`／`report`。

**[`../scripts/gear_combo_es_poe1.py`](../scripts/gear_combo_es_poe1.py)** —— 2026-08-02 建立，
以「10 divine 配頭盔／手套／戒指／腰帶，最大化 `2.20×生命 + 2.41×ES`，
同時滿足三抗＋力量＋敏捷」建成。與上面那支的差異：

- **目標函數是加權和**，且 **ES 要分兩種來源讀**（護甲類 `extended.es`、飾品類詞綴文字）——
  見 [knowledge/slots.md](knowledge/slots.md) 的 ES 章節，弄反會整個部位算成 0。
- **五條約束軸**（火／冰／雷／力量／敏捷）。B 世代那套 3-D 後綴最大值查表在 5 軸下會爆掉，
  所以改用向量化 join＋兩個精確上界，細節與收斂實測見
  [`../common/optimizer-algorithms.md`](../common/optimizer-algorithms.md) 的 **C 世代**。
- 多兩個子命令：**`deep`**（不重搜、把每個池子從 30 件延伸到 100 件）與
  **`negatives`**（把樣本裡的負面詞綴分類後列出來**問使用者**要禁哪些——
  黑名單綁流派，每次都要重問，見 [knowledge/crafting.md](knowledge/crafting.md)）。
- **`POE_FAST` 預設 280**（不是 0）：這題的完全精確解跑不完。2026-08-10 熱迴圈優化後
  重新量過，280 是「達到收斂頭條」的第一階（280 與 400 的頭條都是 3204），
  完整七階只要 296 秒。**130 階已經不再收斂**（只有 3160）——收斂階是資料的性質，
  改過候選評分（例如工藝置換的修正）就要重新量。求解前會印 ETA。
- 多一個子命令 **`reparse`**：快取只存詞綴文字、不存工藝旗標，所以牽涉工藝判定的
  解析修正無法回溯套用，要用它重抓（只抓「可能帶工藝」的列，不是整池）。

**[`../scripts/gear_combo_res4_poe1.py`](../scripts/gear_combo_res4_poe1.py)** —— 2026-09-05 建立，
以「10 divine 配鞋子／手套／胸甲／雙戒，四軸（火／冰／雷／**混沌**）補到位、最大化總生命」建成。
**已實際採買驗證（2026-09-05）**：使用者買下 CP 甜蜜點那套（4200c 預算只花 1158c）並回報
「運作良好都有達到我的要求」——混沌軸、戒指的工藝扣除、同色工藝互斥、胸甲 Life 詞綴閘門、
價格換算，整條鏈都對得上實機，不只是對得上 selftest。
與前兩支的差異，每一項都是前兩支做不到而不是重複造輪子：

- **混沌抗是約束軸**。前兩支**完全不解析混沌**——`gear_combo_es_poe1.py` 還特地把
  `+#% to Fire and Chaos Resistances` 的混沌那一半丟掉（註解寫 "chaos res is out of scope"）。
- **五個部位，其中兩個是同一個 category**（雙戒）。戒指對必須是**兩筆不同掛單**，
  所以 J 半邊不是 `combine()` 而是 `ring_pairs()`，會跳過 `a["id"] == b["id"]`。
  selftest 也多驗這一條。
- **每個部位有自己的硬條件**（Shaper 影響、移速、CDR、神廟複合詞、「完全不能有 Life 詞綴」、
  「要留一格前綴給工藝」），所以沒有單一的 `q()`，改成 `slot_query(slot, stats)`。
- **同色單元素抗性互斥已實作**（前兩支未修，見 [knowledge/crafting.md](knowledge/crafting.md)）：
  `_scan_mods()` 記下每條抗性的**詞綴群組**，`expand_crafts()` 拒絕群組已被原生佔用的工藝。
- **工藝展開含元素＋混沌複合（15/15）**，因為**工藝台沒有純混沌抗**這條。
- 目標函數是純生命，ES／閃避只報告不計分。多一個環境變數 **`POE_TEMPLE=fire`**（見下）。
- 精確解（`POE_FAST=0`）在這題**跑得完**（候選集比 ES 那題小），實測 200／400／800／0 四階同分。

要點：**端點、欄位名、stat id、詞綴正則都是 POE1 profile**（別跟 `gear_combo_optimizer_poe2.py` 混用）；
求解器是精確解（抗性截頂＋Pareto＋3-D 後綴最大值），`POE_FAST=75` 可在 6 秒內重算；
POESESSID 過期時會自動改走已登入瀏覽器的 in-page fetch。方法論與實測數據見
[`../common/tricks.md`](../common/tricks.md) 與 [knowledge/slots.md](knowledge/slots.md)。

## Knowledge base

⚠ **先分辨題型**：使用者講「重練／練小號／twink／速通劇情」時，那**不是** CP 值配裝題——
目標函數是最小化通關時間、硬約束是需求等級而非價格、而且沒有配裝空間。
直接讀 [knowledge/releveling.md](knowledge/releveling.md)，**不要動求解器**。

`poe1/knowledge/` 目前有 [exchange-rates.md](knowledge/exchange-rates.md)（匯率來源）、
[releveling.md](knowledge/releveling.md)（**重練套路**：需求等級主軸、3.29 穢生陷阱、力量猛射×學富之筆全套清單與核心天賦排除法）、[slots.md](knowledge/slots.md)（腰帶詞綴位拆解 + **頭盔／手套／項鍊／戒指／腰帶六部位的生命×三抗天花板**）、[market.md](knowledge/market.md)（腰帶高端階梯 + **1–10c 低價帶市場形狀與通貨換算表**）。使用者教的每一條 POE1 事實都寫進這裡，並在 [INDEX.md](knowledge/INDEX.md) 加一行中英雙語關鍵字。分類原則見 [`../SKILL.md`](../SKILL.md)：**換一款遊戲還成立的才放 `../common/`，其餘全部留在這裡。**
