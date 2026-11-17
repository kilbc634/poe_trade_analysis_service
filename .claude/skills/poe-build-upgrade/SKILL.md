---
name: poe-build-upgrade
description: End-to-end workflow for upgrading or converting a Path of Exile 1 character within a budget — take the player's real character and a reference build (an author's PoB, a guide), measure every candidate purchase in Path of Building, price it on the trade site, and deliver a purchase list. Use when the user asks to "upgrade my build with X chaos", "convert to crit / to another skill like this author did", "what should I buy first", "is this item worth it for my character", or wants staged shopping during league start when listings move within minutes. This skill is the ORCHESTRATION layer — it decides the order of work, what to measure, when a fast heuristic beats an exact solver, and records the mistakes that only appear when PoB and the trade site are combined. Tool mechanics stay in their own skills — pob-operator (driving PoB), poe-trade-query (searches, crafting rules, exact solvers), poe-wiki (mechanics), poe-ninja-builds (meta).
---

> **POE1 only**｜首次實戰：**2026-11-16～17**（Covens 聯盟開季第 3～4 天，PoB Community 2.67.2，天賦樹 3.29）
> 一隻 Lv82 銳眼從非暴擊閃電箭矢轉成暴擊彈幕．齊射，兩階段共約 290c，
> PoB 預估結合秒傷 18 萬 → 718 萬（這個數字還含三樣當時尚未購買的佔位物品）。
> POE2 沒有實測過，不得直接套用。

# 預算內升級／轉型一隻角色

這個 skill 記的是**流程與經驗**，不是工具用法。
要操作 PoB 讀 `pob-operator`；要查價、查工藝規則、用精確求解器讀 `poe-trade-query`。

**沒有附腳本。** 每次的條件都不一樣（部位、硬條件、目標），照下面的流程現寫比改舊腳本快，
而且這次留下的腳本裡有好幾個是修過錯才對的——直接沿用只會把沒發現的錯一起帶走。

---

## 先判斷：這題要快還是要準

| 情境 | 做法 |
|---|---|
| 開季前幾天、掛單幾十分鐘就換一輪、預算是幾百 chaos | **快速解**（本檔的流程）。整輪 5～10 分鐘，答案出來時貨還在 |
| 季中後期、單件數 divine 以上、掛單穩定 | 精確求解器（`poe-trade-query` 的 `gear_combo_*`），多花幾十分鐘值得 |
| 部位之間沒有互補關係（傳奇、武器、寶石） | **不需要求解**，各自沿「價格對傷害」的曲線挑 |

判斷依據是實測：這次第一階段的 11 件清單交出去後約 **40 分鐘，使用者回報其中三類被買走**，
備選裡也有兩件在半小時內改了價。
求解花的時間如果比貨的壽命長，最佳解沒有意義。

細節與數字 → [knowledge/fast-solve.md](knowledge/fast-solve.md)

---

## 流程

### 0. 把條件問清楚，而且之後要驗算

要拿到的東西：預算、分幾階段買、哪些是硬條件（抗性、壓制、移速、連數）、其餘追求什麼（傷害或生命）、
量測假設（打什麼等級的頭目、距離、哪些狀態視為常駐）。

**使用者指定的配法也要算一次。** 這次使用者指定「胸甲不帶生命＋15% 生命專精」，實算比帶生命的胸甲少
157 生命（見 [knowledge/pitfalls.md](knowledge/pitfalls.md)）。做法是兩種都解、把數字並排交給他選，
不是照做也不是擅自改掉。

負面詞綴要不要排除，**每個流派都要重新問**（`poe-trade-query` 的 `poe1/knowledge/crafting.md` 有分類法）。

### 1. 建立基準：「範本 build 套上使用者的現實」

1. **匯入使用者的角色**（官網公開資料，三支 `character-window` 端點，交給 PoB 的 `ImportTab` 函式）。
   公開資料**不含盜賊選擇和萬神殿**，一定要問。
2. **取得範本**（作者的 PoB 連結、影片說明欄、文檔）。
3. **以範本為底，把使用者的現實放回去**，而不是在使用者的 build 上一項一項改：
   範本已經有整套寶石連結、天賦、昇華，從那邊出發只要換掉「使用者沒有的東西」。要換的有：
   - 等級、盜賊、使用者自己的 PoB 設定
   - 寶石等級（使用者已有的沿用他的等級，新買的給一個保守值）
   - **範本上所有使用者沒有的物品——包含天賦樹上的珠寶**（最容易漏，見 pitfalls）
   - 天賦點數：範本通常等級比較高。裁到使用者的點數時，**只暫緩純傷害的點**，
     生命、屬性、壓制的點不動，並把暫緩的點依傷害排成「之後升級的補回順序」

存成一份新檔交給使用者對照。**不要覆蓋使用者自己的檔案**；他之後會把買到的東西匯入這份檔，
那時它就變成他的檔案，後續一律只讀。

### 2. 統一量測條件，再開始比

- **頭目等級、距離、常駐狀態**先跟使用者對齊。同一隻角色在 Uber 和巔峰頭目設定下秒傷差 3 倍以上，
  沒對齊的數字不能互相比。
- **感電效果要算到自洽**，不要沿用使用者或作者手填的數字（見 pitfalls）。
- **主要指標先講清楚。** 有幻影射手這類分身時，`TotalDPS` 只有本體，`CombinedDPS` 才是作者口中的數字。
- **每次只換一樣東西。** 量某一件的價值時，其他部位必須完全不動。

### 3. 把要買的東西分成兩類

| 類別 | 例子 | 怎麼選 |
|---|---|---|
| **彼此無關** | 傳奇、弓、箭袋、技能寶石、腰帶和它的珠寶 | 各自量完，沿價格對傷害的前緣往上走，只在「每多 1% 傷害的價錢」還合理時升級 |
| **互相補位** | 補抗性、屬性、生命的稀有裝 | 要一起解：一件少了智慧，另一件就得補 |

**先買無關的那一類**（它們決定了傷害，也決定了剩下的缺口有多大），再解互補的那一類。
傳奇換上去之後抗性和屬性通常會瞬間崩掉，這是預期中的事；先量出缺口，第二階段才知道要補什麼。

### 4. 抓候選

- **每次都重抓**，不沿用幾小時前的價格。
- **硬條件寫進查詢**（部位、連數、閃避底、移速、未汙染），讓回來的都能用。
- **每個部位抓兩池**：一池「有空後綴或已有工藝後綴」（賣相差、便宜、可以自己補），一池不限。
- 排序用加權總分。**權重是憑判斷設的，只影響哪些件被抓回來**，最後選誰由 PoB 決定。
- 需要「沒有某類詞綴」時，查詢端的 `not` 群組只能擋掉大部分，**抓回來還要在本地用文字再篩一次**。

### 5. 在 PoB 逐件實測

把每件候選換進對應部位重算，記下它讓生命、三抗、屬性、壓制、秒傷各變多少。
傷害類的詞綴彼此加乘、和天賦互動，**用眼睛或用權重估都不可靠**——這次同價位的弓實測差了 7%。

能上工藝的件要把工藝也算進去（規則與數值在 `poe-trade-query` 的 `crafting.md`）：
已有工藝的先移除、同色單抗互斥、鞋子的工藝位若要留給特定詞綴就只剩一種選擇。

### 6. 求解

無關的那一類不用解。互補的那一類用快速解 → [knowledge/fast-solve.md](knowledge/fast-solve.md)。

門檻類的條件（抗性、屬性、壓制）當成**硬條件**，不要跟生命、傷害一起加權；
使用者說「抗性補滿，其餘生命越高越好」的意思就是這樣。

### 7. 驗證與交付

1. **把選出來的整套連同工藝詞綴真的放進 PoB 重算**，確認每個條件都過。
2. **存檔之後重新載入檢查一次**（見 pitfalls，這一步這次救回了兩個版本的錯）。
3. **交付前逐件確認還在架、價格沒變。**
4. 清單照 `poe-trade-query/common/delivery.md` 的格式寫成檔案；每件都附「為什麼是這件」和備選。
5. 講清楚哪些是實測、哪些是假設、哪些沒查。

### 8. 採買

- **使用者自己照清單買**：適合互補的那一類，他要整套確認過才動手。
- **逐件傳送**：對 Instant Buyout 掛單送 `hideout_token` 可以直接把角色傳到賣家藏身處
  （端點與實作見 `script/wholesalers.py`）。**只適合彼此無關的部位**，而且要使用者明確要求、人在線上待命。
  做法是當下重查、挑一件、立刻送出，回報賣家、倉庫頁名稱和格子座標；同一賣家有多件同名物品時要講明認哪個數值。
- 被買走就重查那一類，不要回頭翻舊清單。

買完請使用者把東西匯入 PoB，**再讀一次他的檔案核對**：實際數值對不對、有沒有漏詞綴、
哪些部位還是佔位裝備。這次核對出一顆珠寶匯入時少了一條詞綴。

---

## 跟使用者溝通的幾個習慣

- **每個數字都講前提**（頭目等級、感電值、距離）。前提改了就整批重算，不要混用。
- **版本要乾淨。** 修正之後整份重寫，不要在舊表上打補丁；舊的 PoB 檔標明作廢或刪掉。
- **自己的錯要先講。** 這次有四個結論後來被推翻（見 pitfalls），每一個都是在回覆開頭就說明，
  並交代影響多大。
- **遊戲內要搜尋的名稱中英並列**，英文是使用者實際貼進遊戲的字。

---

## 知識庫

- [knowledge/INDEX.md](knowledge/INDEX.md) — 先 grep 這份
- [knowledge/fast-solve.md](knowledge/fast-solve.md) — 快速解的做法、實測規模與耗時、弱點
- [knowledge/pitfalls.md](knowledge/pitfalls.md) — 串接 PoB 與交易站時踩過的坑
- [knowledge/league-start-market.md](knowledge/league-start-market.md) — 開季市場的實際節奏、甜蜜點怎麼定

新的經驗照 `INDEX.md` 開頭的規則歸檔：**只屬於單一工具的事實寫回那個工具的 skill**，
這裡只收「要兩個以上的工具一起用才會遇到」的事。
