---
name: poedb-mods
description: Read the MODIFIER TABLES on poedb.tw base-item pages — which prefixes and suffixes a base can roll, their tiers, required item levels and spawn weights, including the Delve / Veiled / Corrupted / Synthesis pools. Use whenever a task needs "can this base roll X", "what item level does T1 need", "what are the odds / how many alterations to hit mod X", a crafting cost estimate, or a mod-tier lookup. This skill exists for ONE reason — those tables are rendered by the page's own script, so a plain fetch (WebFetch, curl) returns the page WITHOUT them; the bundled script reads them through a browser. For modifier data poedb is the top authority; never take mod pools or weights from Path of Building's data files (they include legacy and unrollable entries). SCOPE — this skill does NOT govern poedb in general. Everything else on poedb (unique items, base items, keystones and passives, gems, crafting bench, league mechanics…) is ordinary page content that a plain fetch reads fine; keep using poedb freely for those and cross-reference it with poewiki as usual.
allowed-tools: Bash(python:*) Bash(py:*) Bash(playwright-cli:*) Read Grep
---

> **POE1**（`poedb.tw`）｜最後實測：**2026-11-23**（3.30 Covens）
> POE2 的資料在 `poe2db.tw`，**尚未實測**，不要直接把本檔的頁面結構套過去。

# 用 poedb 查詞綴表（詞綴池、階級、物品等級、權重）

## 這個 skill 的範圍：只管詞綴表，不管 poedb 的其他用途

poedb 是整個遊戲的資料庫，不是只有詞綴。**這個 skill 只處理一件需要特殊做法的事：基底頁上的前後綴表。**
其餘內容照平常的方式查，不受本檔任何規則限制：

| 要查的東西 | 怎麼查 |
|---|---|
| 某基底的前後綴、階級、物品等級、權重 | **本 skill**（要用瀏覽器，見下） |
| 傳奇裝備、物品基底的屬性與需求、核心天賦與天賦、技能寶石、工藝台清單、聯盟機制等 | 直接讀 poedb 的頁面即可（WebFetch／curl 都拿得到內容），並照慣例和 poewiki 互相對照 |

2026-11-23 實測，單純抓網頁就讀得到內容的頁面：傳奇（`Subsume_the_Source`，含詞綴與掉落來源）、
核心天賦（`Supreme_Ostentation`）、基底（`Faithful_Helmet` 的需求與防禦值）、技能寶石（`Flicker_Strike`）。
同一個基底頁上，只有「Modifiers Calc」的前後綴表抓不到。

poedb 和 poewiki 是並列的兩個權威來源（見 `poe-wiki`）：查資料時兩邊來回參照是正常做法。
「這一季還拿不拿得到」以 poewiki 的說明較清楚；新賽季剛開時 poedb 通常更新得比較快。

## 權威順序

**凡是跟詞綴有關的事，poedb 是最高權威。** 某個基底能骰哪些詞綴、每一階的數值、需要的物品等級、生成權重、機率，一律以 poedb 為準。玩家自己就是這樣查的。

- **不要從 Path of Building 的資料檔拿詞綴池或權重。** PoB 的 `Data/Mod*.lua` 收錄了絕版與實際骰不出來的條目，拿來算機率會算錯。
  實例（2026-11-23）：Searching Eye Jewel 的後綴總權重，PoB 資料加總是 47,775，poedb 是 38,875，照 PoB 算會把機率低估約 19%。
- **數字對不上時以 poedb 為準**，不必兩邊折衷，也不必先去查誰對。
- 這條順序只針對詞綴數據。其他類型的資料沒有「poedb 壓過 poewiki」這回事，照上一節來回參照。

## 先知道這件事：單純抓網頁看不到詞綴表

| 存取方式 | 結果 |
|---|---|
| WebFetch／curl 抓 `https://poedb.tw/us/<頁面>` | 回 200，有標題、基底資訊、腐化隱性等表格，**但沒有前後綴表** |
| 瀏覽器開同一頁（無頭也可以） | 正常，詞綴表在「Modifiers Calc」區塊 |

看到抓回來的頁面沒有詞綴表時，**那不是「poedb 沒有這份資料」，是抓法不對**。不要就此回報查不到，更不要改拿 PoB 的資料頂替。

## 用法

腳本在這個 skill 的目錄裡：`.claude/skills/poedb-mods/poedb_mods.py`（Python 3.8+，只用標準函式庫；需要 `playwright-cli` 指令）。

```bash
python poedb_mods.py Searching_Eye_Jewel                                   # 總覽：有哪些詞綴組、各組總權重
python poedb_mods.py Searching_Eye_Jewel --group "Base Suffix"             # 一組裡的所有詞綴家族
python poedb_mods.py Searching_Eye_Jewel --group "Base Suffix" --find accuracy --ilvl 85
python poedb_mods.py Vaal_Regalia --group "Base Prefix" --tiers            # 連每一階都列出
python poedb_mods.py https://poedb.tw/us/Stygian_Vise --json               # 原始資料，給其他腳本接
```

| 參數 | 說明 |
|---|---|
| 頁面 | poedb 的頁面名稱（網址最後一段，空白用底線）或完整網址 |
| `--group` | 詞綴組名稱，不分大小寫，可只打一部分。不給就印總覽 |
| `--find` | 只列文字含這個字的家族，並自動展開它的每一階 |
| `--ilvl N` | 你手上基底的物品等級。高於它的階會被排除，**權重與機率會重新計算** |
| `--tiers` | 展開每個家族的所有階 |
| `--lang` | 只給頁面名稱時用的語系段，預設 `us`。物品英文名查不到時可試 `tw` |
| `--refresh` | 不讀快取（快取 6 小時，放在系統暫存目錄的 `poedb-mods/`） |
| `--headed` | 開有視窗的瀏覽器。無頭讀不到時才需要 |

頁面名稱就是基底的英文名：`Searching_Eye_Jewel`、`Vaal_Regalia`、`Two-Stone_Ring`。不確定名稱時先在 poedb 站內搜尋，或從 `poe-trade-query` 的 `items.tsv` 找基底英文名。

### 輸出怎麼讀

```
== Base Suffix | 49 families | total weight 38875 at item level 85
 weight  chance  ilvl tiers  top tier text [tags]
   3500  9.003%    85     4  +(241—300) to Accuracy Rating [Attack]
            T4   of Steadiness     ilvl 1   weight 1000   2.572% of group  +(31—60) to Accuracy Rating
            T1   of the Deadeye    ilvl 85  weight 500    1.286% of group  +(241—300) to Accuracy Rating
```

- 第一行的 `total weight` 是這一組（例如所有基礎後綴）的總權重，也就是算機率的分母。
- 每個家族一列：家族總權重、佔該組的機率、最高階需要的物品等級、階數、最高階的詞綴文字。
- 展開的每一階：階級、詞綴名稱、物品等級、權重、佔該組的機率。**「某一階的機率」＝ 該階權重 ÷ 該組總權重。**
- 沒給 `--ilvl` 時，數字是「物品等級足夠骰出所有階」的情況，與 poedb 頁面上顯示的一致。

## 詞綴組

一個基底的頁面通常有這幾組，各自是獨立的池子，**總權重不能跨組相加**：

| 組 | 內容 |
|---|---|
| `Base Prefix`／`Base Suffix` | 一般能骰出的前綴與後綴。改造石、混沌石、製作估算都用這兩組 |
| `Delve Prefix`／`Delve Suffix` | 化石才會出現的詞綴 |
| `Veiled Prefix`／`Veiled Suffix` | 揭露詞綴 |
| `Corrupted` | 瓦爾寶珠腐化的隱性詞綴 |
| `Synthesis`／`Synthesis Corrupted` | 追憶隱性；poedb 這兩組不標權重，總覽會顯示 0 |

影響力詞綴、精華等其他組，頁面上有就會一起列出來，組名照頁面原文。

## 算機率時的注意事項

- **物品等級一定要帶進去。** 高階詞綴有物品等級門檻，基底等級不夠就骰不出來，同時分母也會變小。用 `--ilvl`。
- **同一家族的各階互斥。** 一件物品上同一家族只會有一階，所以「骰到這個家族的任一階」直接用家族權重。
- **不同基底的權重不同。** 同一條詞綴在不同基底上的權重可能差一倍。
  實例：T1 命中 `+(241—300) to Accuracy Rating` 在 Searching Eye Jewel 是 500／38,875（1.29%），在 Murderous Eye Jewel 是 250／38,475（0.65%）。
- **poedb 給的是「骰一條這種詞綴時」的權重。** 一顆通貨實際會骰幾條、前綴還是後綴，是另一層機率，頁面上沒有。
  例如魔法物品用改造石，社群通用的估計是 50% 只有一條（前後綴各半）、50% 前後綴各一條，所以「有後綴」約 75%。這個數字不是 poedb 的資料，引用時要講明是估計值。
- **回報時把分子、分母、物品等級都寫出來**，讓使用者可以自己對 poedb 的頁面。

## 頁面結構（腳本壞掉時用來修）

2026-11-23 實測的結構，擷取邏輯在 `poedb_mods.js`：

- 每一組的標題是 `h5.identify-title`，文字就是組名；它的父元素包住整組。
- 組裡每個詞綴家族是一個 `.mod-title` 元素，`data-gengroup` 是家族代號。右側三個徽章：
  `.badge.bg-danger` 是家族總權重（它的 `data-bs-title` 是 poedb 自己算的機率，例如 `1.286%`），
  `.badge.bg-secondary` 是最高階的物品等級，`.badge.bg-success` 是階數。
- `.mod-title` 的 `data-bs-target` 指向一個 `#collapse…` 區塊，裡面每個 `tr` 是一階，
  儲存格依序是階級（T1 最高）、詞綴名稱、物品等級、詞綴文字（內含標籤徽章與 `.badge.bg-danger` 的該階權重）。階的排列是由低到高。
- 這些元素在頁面載入後由腳本產生，擷取前要等 `.mod-title` 出現。

驗證過的一致性：每個家族的權重等於它各階權重的總和；腳本算出的機率與頁面上 `data-bs-title` 的數字相同（Searching Eye 的 T1 命中兩邊都是 1.286%）。

## 手動操作（腳本不能用時）

```bash
playwright-cli -s=poedb open https://poedb.tw/us/Searching_Eye_Jewel
playwright-cli -s=poedb --raw run-code --filename=.claude/skills/poedb-mods/poedb_mods.js > out.json
playwright-cli -s=poedb close
```

頁內要執行的 JS 一律放在檔案裡用 `run-code --filename` 帶入，不要塞在命令列（Windows 的命令列會改掉字串裡的 `%` 等字元）。

用量保持在一個人查資料的程度：一次任務查幾頁，腳本有 6 小時快取，同一頁不會重複開。
