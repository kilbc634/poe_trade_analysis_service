---
name: poe-ninja-builds
description: Analyse Path of Exile 1 build META and archetype trends on poe.ninja (https://poe.ninja/poe1/builds) — which ascendancies/skills/items/passives people actually play, and how those correlate. Use whenever the user asks what a class is playing, what a given skill's builds look like, how popular an archetype is, what gear/keystones a build tends to run, or how the meta shifted over a league. This is BUILD/META analysis, not price checking — for prices and item searches use poe-trade-query instead. Drives the site through its UI/URL; ships the full filter-parameter map so you can jump straight to a filtered view without clicking.
allowed-tools: Bash(playwright-cli:*) Bash(npx:*) Read Grep
---

> ⛔ **POE1 ONLY**（`/poe1/builds`）｜聯盟基準：**Allflame**（3.29）｜最後實測：**2026-08-30**
> POE2 在 `/poe2/builds`，**尚未實測**，本檔的參數名不得直接套過去。

# poe.ninja 流派取向分析（POE1）

這個 skill 讓你回答「大家在玩什麼、怎麼玩」這類問題：某職業的主流技能是什麼、
玩某個技能的人點哪些核心天賦、某件裝備的使用率、開聯盟第一週到第五週流派怎麼漂。

**不做查價。** 價格、掛單、物品搜尋走 `poe-trade-query` + `open-poe-trade`。
瀏覽器機制走 `playwright-cli`。

---

## 心智模型：這是樞紐分析表，不是排行榜

整頁的關鍵在一句話：**左側篩選面板上的每個百分比，都是「在當前篩選結果之內」重算的條件機率。**

| | 全聯盟 124,493 人 | 篩 `class=Elementalist` 後 20,548 人 |
|---|--:|--:|
| Winter Orb | 9% | **18%** |
| Liege of the Primordial | —（未進前 12） | **97%** |
| Mastermind of Discord | — | **66%** |

所以取向分析的做法是**疊條件、讀面板**，不是把原始資料抓回來自己算：
先鎖住你關心的那一群人（職業／技能／裝備／天賦），再看面板上其他類別浮出什麼。
「玩 Winter Orb 的 Elementalist 幾乎都點 Liege of the Primordial」這種結論，
面板直接就寫在那裡。

（數字為 2026-08-30 Allflame 快照 `1453-20260829-10410`，僅供理解口徑，別當長期事實引用。）

---

## 頁面地圖

| 路徑 | 內容 |
|---|---|
| `/poe1/builds` | 聯盟選單（Challenge／Standard／Private／Streamers）＋各聯盟 Top Classes 預覽卡，卡片直接連到帶篩選的 URL |
| `/poe1/builds/{league}` | **主戰場**：左欄職業分佈、中欄 16 組篩選、右欄結果表 |
| `/poe1/builds/{league}/character/{account}-{disc}/{charname}?i={rank}` | 個別角色：完整數值、Ascendancy & Keystones、Masteries、Runegrafts、Skill DPS Estimation、**Import Code for Path of Building**、每件裝備的 Search on Trade |

`{league}` 是 slug 不是顯示名：`allflame`／`allflamehc`／`allflamessf`／`allflamehcssf`／
`allflamer`（Ruthless）／`allflamehcr`／`allflamessfr`／`allflamehcssfr`／`standard`／`streamers`。
過去聯盟與 28 個私人聯盟在 `/poe1/builds` 的選單裡，或頁面頂端的 League 下拉。

---

## 操作方式：組 URL，不要點

**所有篩選狀態都寫在 query string。** 直接 `goto` 一條組好的 URL，比逐格點擊穩得多也省請求——
點擊會遇到 ref 失效（見 gotchas），組 URL 不會。

```bash
playwright-cli open "https://poe.ninja/poe1/builds/allflame?class=Occultist&skills=Winter+Orb&keypassives=Chaos+Inoculation&min-level=95&columns=character,level,dps,ehp"
```

### 語法規則（2026-08-30 實測）

| 規則 | 寫法 | 實測 |
|---|---|---|
| 單值 | `?class=Elementalist` | 20,548 |
| 多值 | 逗號分隔 `?items=Mageblood,Watcher's+Eye` | 前端拆成重複參數 `items=A&items=B` 送 API |
| **多值＝AND**（除 `class` 外全部） | `?skills=Winter+Orb,Righteous+Fire` | 10,624 ∩ 6,329 = **5** |
| **`class` 是 OR**（一角只有一個職業，AND 會是 0，站方特例處理） | `?class=Elementalist,Occultist` | 20,548 ＋ 13,418 = **33,966**（加總精確吻合） |
| 排除 | 值前加 `!` | `?skills=!Winter+Orb` → 113,869（= 124,493 − 10,624，剛好） |
| 空格 | `+` 或 `%20` 皆可 | |

UI 上對應的是**三態格子**：點一下 include，格子浮出 `Exclude` 與 `Clear filter` 兩顆小按鈕。

### 參數總表

完整 16 組篩選類別 → 參數名，見 [`references/filters.tsv`](references/filters.tsv)。
最常用的幾個：

| 類別 | 參數 |
|---|---|
| 職業／昇華 | `class`（**OR**；base class 與 ascendancy 同一格，如 `Witch` 或 `Occultist`） |
| 主技能 | `skills` |
| 裝備／獨特物 | `items` |
| 核心天賦 | `keypassives` |
| 敷油 | `anointed` |
| 全部寶石（含輔助） | `allgems` |

**視圖與範圍**（不屬於那 16 組）：

| 參數 | 值 |
|---|---|
| `type` | `exp`（經驗榜，預設）｜`depthsolo`（深度榜）。**換 type 會換一組 snapshot id** |
| `timemachine` | 空＝最新；`week-1`…`week-5`；`day-1`…`day-6`；`hour-3`／`hour-6`／`hour-12`／`hour-18` |
| `heatmap` | `true` = 開天賦熱力圖（**可深連結**） |
| `name` | 角色名搜尋 |
| `sort` | 欄位 slug（如 `sort=dps`）。預設依榜單排序，`sort=life` 等 |
| `sort-asc` | `true` = 升冪；省略＝降冪 |
| `min-level` / `max-level` | 80–100 |
| `min-life` / `max-life`、`min-energyshield` / `max-energyshield`、`min-ehp` / `max-ehp`、`min-dps` / `max-dps` | 數值 |
| `columns` | **有序**的欄位 slug 逗號串，如 `character,level,dps,ehp`。預設 `character,level,life,energyshield,ehp,dps,keystoneskill` |

52 個可選欄位的 label → slug 對照，見 [`references/columns.tsv`](references/columns.tsv)。

⚠ Items 類別裡的 `Only show items of type` 下拉（All／Amulet／Belt／…／Tincture／Weapon）
**不寫入 URL** —— 它只是把左側 Items 清單縮到該部位，方便你找，不是查詢條件。

---

## 負載與分寸

網路面實測：**一次篩選變動 = 一支聚合請求**

```
GET /poe1/api/builds/{snapshotId}/search?class=…&overview={league}&type=exp
```

另有進站抓一次的 `~20 支 /poe1/api/builds/dictionary/{sha1}`（內容定址、可長快取）
與一支 `/poe1/api/data/index-state`。角色頁是 `…/character?account=…&name=…`。

也就是說走 UI／組 URL 的成本就是「人點幾下就幾個請求」，跟後端輪詢式抽取不是同一個量級。

但要知道自己站在哪：poe.ninja 的 [API 說明](https://poe.ninja/docs/api) 明寫
builds／profiles 端點是 internal、undocumented、**not available for third-party use**，
理由是負載重、且會繞過玩家隱藏角色的隱私選擇。公開支援的只有 economy 那幾支。

**所以：以人的節奏用網站，不要把那支 `search` 端點當自己的後端。**
- 一次分析打幾次、幾十次篩選是正常瀏覽；不要寫迴圈掃聯盟／掃全技能。
- 結果就地讀完、就地落成結論，不要建鏡像資料庫。
- 不要批次抓個別角色頁。要單一角色的完整配置，用頁面上的 **Copy Path of Building** 出口。
- `poe.ninja/robots.txt` 目前回 404（SPA catch-all），沒有 crawl 指示可循 —— 規範以上面那段政策文字為準。

---

## 知識庫

隨用隨長，**grep 完再讀**，別整包載入：[`knowledge/INDEX.md`](knowledge/INDEX.md)

- [`knowledge/analysis.md`](knowledge/analysis.md) — 怎麼用條件百分比做取向分析、樣本數怎麼看、常見問句對應的篩選組合
- [`knowledge/gotchas.md`](knowledge/gotchas.md) — 操作坑（Loading 空白快照、ref 失效靜默失敗、AND/OR 不對稱…）

使用者教你新事實時：附到對應的 knowledge 檔、在 INDEX 加一行中英雙語關鍵字、更新檔頭日期。
**任何量到的數字都要標日期與聯盟** —— 流派分佈每個聯盟重來一次。
