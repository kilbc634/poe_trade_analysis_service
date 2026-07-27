> ⛔ **POE1 ONLY** ｜ 聯盟：**Allflame**（遊戲版本未記錄）｜ 最後整理：**2026-07-28**
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
- **搜尋回應存 100 個 result hash**（與 POE2 相同）——深抓價格階梯可用後段。
- **`status.option` 五個值，與 POE2 完全相同**：`securable`（Instant Buyout）/ `available`（Instant Buyout and In Person）/ `onlineleague`（In Person, Online in League）/ `online`（In Person, Online）/ `any`。
- **限流與 POE2 共用同一個池**（實測交錯打兩款遊戲，`trade-search-request-limit` 的 IP 計數連續累加）——詳見 [`../common/tricks.md`](../common/tricks.md)。
- **fetch 回傳結構**：`item.extended` 有 `ev`/`ar`/`es`/`ev_aug`/`base_defence_percentile`/`hashes`/`text`；`item.sockets` 存在（POE1 的插槽/連線系統）；`listing.price` 形如 `{type:'~b/o', amount:7, currency:'chaos'}`；有 `whisper_token`／`hideout_token`；稀有裝另有 `note`（賣家標價註記）、`requirements`、`properties`。

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
- `extended.mods` 在這件樣本是**空的**（`{}`）——階級資訊在各詞綴物件裡，不在 extended 底下。
- **描述文字是純文字，沒有內嵌 wiki 連結括號**（`+31% to Fire Resistance`、`+128 to maximum Life`）。這件樣本的 5 條詞綴都沒有；若之後遇到含括號的再補記。
- **whisper / 前往藏身處：`POST /api/trade/whisper`**，body `{"token":"<JWT>"}`（token 取自 fetch 回傳的 `listing.whisper_token` / `listing.hideout_token`）。角色**離線時回 `400 "Your account must be in-game to use this feature"`**，不會對賣家送出任何東西；線上時會真的執行。實作範例見 [`script/scavenger.py`](../../../../script/scavenger.py)。

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
| `socket_filters` | `sockets`、`links` |
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

⚠ **`weight` / `weight2` 實測會撞複雜度上限**：即使只放一條 explicit 詞綴，API 仍回 `Query is too complex. Please reduce the amount of filters used.`（already authenticated 時依然如此）。型別名本身是有效的——送假值 `xyzzy` 會回 `Invalid statgroup type type`，這兩個回的是複雜度錯誤，兩者不同。加權查詢要能跑得先想辦法壓複雜度。

## 參考表（`references/`，2026-07-27 產出）

從交易頁 localStorage 快取產生，非 API 直取——作法見 [`references/README.md`](references/README.md)。

| 檔案 | 內容 | 筆數 |
|---|---|--:|
| `stats.tsv` | `group<TAB>id<TAB>text` | 17325 |
| `items.tsv` | `category<TAB>name<TAB>type<TAB>flags`（唯一裝有 name，基底只有 type） | 5997（含 1544 唯一裝） |
| `static.tsv` | `群組<TAB>id<TAB>名稱`（通貨、碎片、精華等） | 1433 |

## 待驗證清單（每一項都是 ❓）

> **優先度低（使用者 2026-07-27 判定）** —— 這幾項實務上很少用到，**不要主動花時間去補**。等真的碰到需求時再照下面的線索驗一次就好。

- ❓ **`weight` / `weight2` 要怎麼壓到複雜度上限以下才跑得動**（見上）。
- ❓ **`crucible` / `mercenary` 兩種群組的條目結構**——型別名確定了，但群組內 filters 長什麼樣沒看過。這兩種在 `references/stats.tsv` 各有 2492 / 534 條專屬詞綴。
- ❓ **fractured / synthesised / scourge / veiled 等其他旗標的回傳長相**。crafted 已確認（見上），其餘照同樣方法抓一件比對即可。

*（2026-07-28 已結案：`trade_filters.account` 的值形狀、`price.option` 與 `category.option` 的完整清單、結果頁 URL 格式，全部實測完畢並寫進上面各節。）*

## Knowledge base

`poe1/knowledge/` 目前有 [exchange-rates.md](knowledge/exchange-rates.md)（匯率來源）、[slots.md](knowledge/slots.md)、[market.md](knowledge/market.md)（兩者目前**只有腰帶**，不要往其他部位推論）。使用者教的每一條 POE1 事實都寫進這裡，並在 [INDEX.md](knowledge/INDEX.md) 加一行中英雙語關鍵字。分類原則見 [`../SKILL.md`](../SKILL.md)：**換一款遊戲還成立的才放 `../common/`，其餘全部留在這裡。**
