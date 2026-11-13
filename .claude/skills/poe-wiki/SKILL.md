---
name: poe-wiki
description: Read the Path of Exile wiki (poewiki.net) — the community's authoritative reference for game mechanics, item and gem details, and above all whether something still exists in the current league (drop-disabled / legacy / removed in which patch). Use whenever a task needs a mechanic confirmed ("does X stack with Y", "what exactly does this keyword do"), an item's or gem's source or availability checked, a list page read (tattoos, uniques, runegrafts…), or structured item data queried. The wiki's article pages refuse automated clients (bot protection), so do NOT WebFetch or open them in a browser — this skill reads the same content through the wiki's own API, which is open. NOT for prices (poe-trade-query), popularity/META (poe-ninja-builds) or damage maths (pob-operator); mod pools and tier ranges are still best read on poedb.tw.
allowed-tools: Bash(python:*) Bash(py:*) Read Grep
---

> **POE1**（`www.poewiki.net`）｜最後實測：**2026-11-13**（遊戲版本 3.30 準備期）
> POE2 的 wiki 在 `www.poe2wiki.net`，**尚未實測**，不要直接把本檔的網址與表格名套過去。

# 讀 Path of Exile Wiki（poewiki.net）

poewiki 和 poedb 是玩家公認的兩個權威來源。機制怎麼運作、兩個效果會不會疊加、一件物品從哪裡來、**這一季還拿不拿得到**，wiki 通常寫得最清楚。

這個 skill 只有一支腳本 `wiki.py`（Python 3.8+，只用標準函式庫），全部走 wiki 的 MediaWiki API。

---

## 先知道這件事：文章頁讀不到，API 讀得到

| 存取方式 | 結果 |
|---|---|
| WebFetch／curl 抓 `https://www.poewiki.net/wiki/<頁面>` | 被防機器人保護（Anubis）直接拒絕，回一頁「Access Denied」 |
| playwright-cli 開同一個網址 | 一樣被拒絕（無頭瀏覽器的 User-Agent 帶 `HeadlessChrome`） |
| `https://www.poewiki.net/w/api.php?...` | **正常**，一般請求即可，不需要任何偽裝 |

所以：

- **不要**去抓 `/wiki/...` 的網址，也不要重試。看到「Access Denied」「Anubis」「403」就是這回事。
- **不要**為了過關去改 User-Agent、換有視窗的瀏覽器或用隱身外掛。站方擋的是自動化瀏覽，API 才是它留給程式的入口。
- 用量保持在「一個人查資料」的程度：一次任務查幾頁到十幾頁。腳本內建每次請求間隔 2 秒（跨行程），不要自己另外開迴圈大量抓。

給使用者或報告引用來源時，仍然寫人看的網址 `https://www.poewiki.net/wiki/<頁面_名稱>`（`page` 指令的輸出開頭會印出來）。

---

## 用法

腳本在這個 skill 的目錄裡：`.claude/skills/poe-wiki/wiki.py`。

```bash
python wiki.py search "Pearl of Tsoatha"            # 找頁面標題
python wiki.py sections "List of tattoos"           # 列出一頁的章節與編號
python wiki.py page "Battlemage"                    # 整頁轉成純文字（表格攤平成一列一行）
python wiki.py page "List of tattoos" --section 2   # 只讀某一節（編號來自 sections）
python wiki.py page "Battlemage" --wikitext         # 要原始 wikitext 時
python wiki.py item "Pearl of Tsoatha" "Unholy Accomplice"   # 這東西這一季還拿得到嗎
python wiki.py fields items                         # 某張資料表有哪些欄位
python wiki.py cargo --tables items --fields "items.name,items.removal_version" \
       --where 'items.class_id="Support Skill Gem" AND items.name LIKE "Awakened%" AND items.drop_enabled=1'
```

任何指令加 `--json`（放在子指令**之前**）會印出 API 的原始回應。

`page` 預設把輸出截在 12,000 字元以免灌爆上下文；長頁面先 `sections` 再用 `--section` 讀需要的那一節，或 `--max 0` 取消截斷後導到檔案再搜尋。

---

## 最常用的三件事

### 1. 確認一件東西這一季拿不拿得到

```bash
python wiki.py item "Pearl of Tsoatha" "Awakened Elemental Focus Support" "Unholy Accomplice"
```

```
Pearl of Tsoatha  [Ring, unique]
    DROP DISABLED — legacy, only exists in permanent leagues (removed 3.30.0)
    released 3.29.0, removed 3.30.0
Awakened Elemental Focus Support  [Support Skill Gem, normal]
    DROP DISABLED — legacy, only exists in permanent leagues (removed 3.28.0)
Unholy Accomplice  [Belt, unique]
    obtainable (drop enabled)
    source: Can drop from Lycia, Herald of the Scourge in the Forbidden Sanctum, …
```

判讀：

- `obtainable (drop enabled)` → 現行版本會掉。`source` 那行是取得方式。
- `DROP DISABLED` → 絕版。只存在於永久聯盟（標準）的舊貨，**新賽季拿不到**。配裝、估價、推薦時都要當成不存在。
- `NOT IN GAME` → 資料裡有但遊戲內沒有（未實裝或活動限定）。
- 名稱要完全相符。輔助寶石的正式名稱以 ` Support` 結尾；打不對時腳本會列出相近的名稱。

**任何要建議別人使用的傳奇、寶石、刺青、特殊通貨，都先過這一步。** 「詞綴合法」不等於「東西拿得到」：poedb 的物品頁通常不標絕版，PoB 的資料庫也照樣收錄絕版物品。

### 2. 讀清單頁（哪些現存、哪些絕版）

清單頁（`List of tattoos`、`List of unique belts`…）通常分成三段：可掉落、`Drop-disabled`、活動限定。先看章節再讀：

```bash
python wiki.py sections "List of tattoos"     # 1. Tattoos / 2. Drop-disabled / 3. Event-only
python wiki.py page "List of tattoos" --section 2
```

要整批篩選時，直接查資料表比讀頁面省：

```bash
python wiki.py cargo --tables items --fields "items.name,items.drop_enabled,items.removal_version" \
       --where 'items.name LIKE "%Tattoo%" AND items.drop_enabled=0' --limit 100
```

### 3. 確認機制

```bash
python wiki.py search "Battlemage Spellblade"
python wiki.py page "Battlemage" --section 1
# → - Battlemage stacks with Spellblade Support.
```

機制頁的 `Mechanics`、`Interactions`、`Version history` 幾節最有料。答案在 wiki 上寫明時，就當成已查證，不必再標「未驗證」。

---

## 資料表（Cargo）速查

`cargo` 指令是對 wiki 背後的結構化資料下查詢，語法接近 SQL。常用的是 `items` 表：

| 欄位 | 內容 |
|---|---|
| `name`、`class_id`、`rarity_id` | 名稱、物品類別（`Ring`、`Belt`、`Support Skill Gem`、`StackableCurrency`…）、稀有度（`normal`／`unique`…） |
| `drop_enabled` | 1 = 現行會掉；0 = 絕版 |
| `is_in_game` | 0 = 遊戲內不存在 |
| `release_version`、`removal_version` | 哪一版加入、哪一版移除 |
| `drop_text`、`drop_areas`、`drop_monsters` | 取得方式 |
| `explicit_stat_text`、`implicit_stat_text`、`stat_text` | 詞綴文字，可以用 `LIKE "%關鍵字%"` 找「有某種效果的物品」 |

- 不確定欄位名時先 `python wiki.py fields <表名>`。查詢用了不存在的欄位，API 只會回一個沒有說明的內部錯誤（`MWException`），不會告訴你是哪一欄。
- 欄位在 `--fields`／`--where` 裡用底線（`items.drop_enabled`），回傳的鍵名卻是空格（`drop enabled`）。
- 同一件物品可能回傳重複的列（例如有多個版本的傳奇）；`item` 指令已經去重，自己下 `cargo` 時可加 `--group "items.name"`。
- 其他表：`tattoos`、`skill_gems`、`skill`、`passive_skills`、`mods`、`areas`…。跨表用 `--tables "items,tattoos" --join "items._pageID=tattoos._pageID"`。

---

## 注意事項

- **清單類頁面的內容是範本即時產生的。** `--wikitext` 只會看到 `{{Drop enabled base item table …}}` 這種範本呼叫，看不到物品；要用預設的渲染輸出。反過來，想知道一張清單是「依什麼條件」產生的，`--wikitext` 裡的 `where=` 就是答案，可以直接搬去 `cargo` 用。
- **wiki 更新比遊戲慢。** 剛開季或剛出 patch notes 時，當季的新內容可能還沒寫進去；新東西以官方 patch notes 和 poedb 為準。`removal_version` 等於即將上線的版本號時，代表「這一版起絕版」。
- **詞綴池、階級數值、製作權重**仍以 poedb.tw 為主，wiki 不是最好的來源。
- 輸出已去掉 wiki 在每個連結後面夾帶的物品提示框；如果看到一段文字後面黏著一大串重複的物品說明，是那個提示框沒被濾掉，改用 `--json` 看原始內容。
- 腳本對外只會連 `www.poewiki.net/w/api.php`，User-Agent 是固定的工具名稱，不帶任何使用者資訊。
