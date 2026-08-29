> ⛔ **POE1 ONLY** ｜最後驗證：**2026-08-30**（Allflame 3.29）

# 用條件百分比做取向分析

## 核心：面板數字是條件機率，不是全域熱度

篩掉一批人之後，左側 16 組面板的百分比**全部就地重算**，分母換成「當前結果集」。
這就是分析引擎本身 —— 你不需要把資料抓回來自己樞紐。

一次量測（2026-08-30，Allflame，`type=exp`，快照 `1453-20260829-10410`）：

| | 無篩選 124,493 | `class=Elementalist` 20,548 |
|---|--:|--:|
| Winter Orb | 9% | 18% |
| Liege of the Primordial | — | 97% |
| Mastermind of Discord | — | 66% |

97% 這種數字要讀成「這是該昇華的定義性選擇」，而不是「這流派很紅」。
反過來，一個在全域 3%、在你篩出來的子集也 3% 的項目，代表它**與這個取向無關**——
沒有訊號也是訊號。

## 標準流程

1. **先鎖群體**，用最能定義問題的那一格：職業（`class`）、主技能（`skills`）或關鍵裝備（`items`）。
2. **看 `Found N characters`**，先確認樣本夠不夠（見下）。
3. **讀其他類別浮出什麼**：`keypassives` 看流派骨架、`items` 看必需裝、
   `allgems` 看輔助配置、`weaponmode` 看武器形態、`secondascendancy` 看血脈取向。
4. **需要對照就換一個條件重跑**，比較同一列數字怎麼變。差異才是結論。

## 樣本數怎麼看

`Found N characters` 是唯一的分母來源，**每次疊條件都要重看**。

- 面板只顯示各類別的**前 12 名**，尾巴看不到。要找特定項目用面板頂端的 `Search filters...` 框。
- 條件疊到 N 只剩兩三位數時，百分比的跳動幅度就已經大過你想量的差異了。
  實測 `skills=Winter+Orb,Righteous+Fire` 只有 **5** 人 —— 那不是「冷門流派」，那是雜訊。
- 榜單本身有下界：`type=exp` 是經驗榜，等級 80 以下不在表內（`min-level` 下拉從 80 起跳）。
  所以任何結論都隱含「在有練起來的角色之中」，不是全體玩家。

## 常見問句 → 篩選組合

| 問題 | 組法 |
|---|---|
| 「X 職業現在都在玩什麼？」 | `?class=X` → 讀 Main Skills 面板 |
| 「玩 Y 技能的人怎麼配？」 | `?skills=Y` → 讀 Passives / Items / All Gems |
| 「Y 技能主要是哪個昇華在玩？」 | `?skills=Y` → 讀左欄職業分佈 |
| 「Z 這件裝備誰在用、值不值得買？」 | `?items=Z` → 讀職業與技能分佈；再 `?items=!Z` 對照同流派沒帶它的人 |
| 「這流派吃不吃 Z？」 | `?class=X&skills=Y` 看 Items 面板的 Z 百分比 |
| 「開聯盟以來怎麼漂？」 | 固定其他條件，掃 `timemachine=day-1 → week-1 → … → week-5 →`（空＝最新） |
| 「硬派玩家怎麼玩？」 | 換聯盟 slug 到 `allflamehc` / `allflamessf`，或 `type=depthsolo` 看深潛榜 |
| 「頂端的人跟中段差在哪？」 | 加 `min-dps` / `min-ehp` 切出頂層，對照未切之前的面板 |

## 兩種榜單的口徑不同

`type=exp`（經驗）與 `type=depthsolo`（深度）**是兩份不同的快照**，各自有 snapshot id。
深度榜的母體是玩深淵的人，流派分佈天生偏移；別把兩邊的百分比並排比較。

## 個別角色

要看一個具體配置，進角色頁，用 **Import Code for Path of Building** 的 Copy to clipboard
把整份 build 帶進 PoB，比在網頁上逐項讀快得多。每件裝備旁還有 Search on Trade，
可以直接接到 `poe-trade-query` 去問價。

**不要批次抓角色頁。** 那是逐一查看的出口，不是資料來源。
