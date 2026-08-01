> ⛔ **POE1 ONLY** ｜ 聯盟：**Allflame** ｜ 最後驗證：**2026-07-28**
> 若 `REALM=poe2`，停止並改讀 `../../poe2/knowledge/`。POE2 沒有同一套工藝台，數值更不可沿用。

# 工藝詞綴（craft bench）— 壓低配裝成本的關鍵

## 核心技巧（使用者教，2026-07-28）

**買「空 1 條後綴」或「已有 1 條工藝後綴」的裝備，抗性自己打上去。**
這種裝備賣相差，所以**明顯比較便宜**——但買回來補一條工藝抗性後，實戰數值可能追平甚至超過
那些原生詞綴齊全的貴貨。這是**降低成本**的手段，不是拉高上限的手段。

前提與規則：

- **抗性詞綴只會出現在後綴（suffix）。** 所以只有後綴的空位才有意義，前綴空著不影響抗性。
- **上工藝的成本幾乎為零**，而且**抹掉舊工藝、換上新的可以無限次重複**。
- **roll 值雖然浮動，但因為能無限重試到滿意為止，估值時直接假設吃到該階最高 roll。**
- **只有未腐化（uncorrupted）的裝備能做工藝。** 腐化裝一律視為沒有工藝空間。

## 三類抗性工藝的上限（依部位）

| 部位 | 單元素 | 雙元素複合 | 元素＋混沌複合 |
|---|--:|--:|--:|
| 手套、鞋子、胸甲、頭盔、腰帶 | **+35%** | **+20%**（各） | **+15%**（元素側） |
| 項鍊、戒指 | **+28%** | **+16%**（各） | **+15%**（元素側） |

- 單元素例：`+(29—35)% to Cold Resistance`
- 雙元素例：`+(17—20)% to Fire and Cold Resistances`（**兩種元素各 +20，總抗性點數 40**）
- 元素混沌例：`+(13—15)% to Lightning and Chaos Resistances`（**pseudo 三抗只計元素那一半**）

**雙元素複合在「總抗性點數」上其實最划算**（20+20 = 40 > 單元素 35），
但如果缺口集中在單一元素（例如只缺火），單元素 35 才是對的選擇。**選哪一種要看缺口分佈，
這正好是聯合求解器該決定的事**，不要預設。

## 項鍊／戒指通常不這樣做（使用者提醒）

兩個原因：**能上的抗性數值較差**（28/16 vs 35/20），而且**這兩個部位的工藝欄位通常留給更值錢的
特殊工藝**。所以實務上這招主要用在 **頭盔／手套／鞋子／胸甲／腰帶**。

## ✅ 正解：在**搜尋階段**就用 pseudo 過濾掉（使用者教，2026-07-28 實測）

**這是首選做法**，比抓回來再逐件解析好得多——池子回來就只剩可工藝的貨，不浪費 fetch 配額，
而且「空幾條後綴」是**站台自己算的**，不是我們從詞綴反推。

用一個 **`count` 群組**把「空後綴」與「已有工藝後綴」當成 OR 條件（滿足其一即可）：

```jsonc
"stats": [
  { "type": "and", "filters": [
      { "id": "pseudo.pseudo_total_life", "value": {"min": 150}, "disabled": false } ] },
  // 「至少滿足下列 1 條」= 有空後綴位，或有一條可抹掉重上的工藝後綴
  { "type": "count", "value": {"min": 1}, "filters": [
      { "id": "pseudo.pseudo_number_of_empty_suffix_mods",   "value": {"min": 1}, "disabled": false },
      { "id": "pseudo.pseudo_number_of_crafted_suffix_mods", "value": {"min": 1}, "disabled": false } ] }
],
"filters": {
  "misc_filters": { "filters": { "corrupted": {"option": "false"} } }   // ← 必加，腐化裝不能工藝
}
```

相關的 pseudo id（`../references/stats.tsv` 實查）：

| id | 顯示文字 |
|---|---|
| `pseudo.pseudo_number_of_empty_suffix_mods` | `# Empty Suffix Modifiers` |
| `pseudo.pseudo_number_of_crafted_suffix_mods` | `# Crafted Suffix Modifiers` |
| `pseudo.pseudo_number_of_empty_prefix_mods` | `# Empty Prefix Modifiers` |
| `pseudo.pseudo_number_of_empty_affix_mods` | `# Empty Modifiers` |
| `pseudo.pseudo_number_of_crafted_mods` | `# Crafted Modifiers` |
| `pseudo.pseudo_number_of_prefix_mods` / `..._suffix_mods` | `# Prefix / Suffix Modifiers` |

**實測（2026-07-28）**：上面這個查詢**回 200，`count` 群組沒有撞複雜度上限**
（與 `weight`/`weight2` 不同，那兩個即使只放一條也會被拒——見 [../QUERY.md](../QUERY.md)）。
`L150 + 未腐化 + count(空後綴|工藝後綴)` 的頭盔在架 **5042 件**，供給非常充足。
撈回前 5 件用下面的 tier 數法交叉驗證，**5/5 都是原生後綴 ≤2，與過濾器完全一致**。

**價格佐證**：那 5 件 L150+ 頭盔的價格是 **2 alch（≈0.14c）／5 alch／1 chaos ×3**——
「賣相差所以便宜」在數字上非常明顯，這正是這招的價值所在。

### ⚠ 估值時別把已有的工藝重複計算

若物件**已經有一條工藝抗性後綴**，它現在顯示的抗性**已經含那條工藝**。既然要抹掉重上，
正確算法是：

```
effective_res = (現有抗性 − 已存在的工藝抗性) + 該部位最佳工藝值
```

辨識現有工藝靠 `flags.crafted` / `domain == "crafted"`（見 [../QUERY.md](../QUERY.md)）。
**只用 count 過濾器是看不出這件事的**，所以解析階段仍然要標記哪幾條是工藝詞綴。

## 備援：從 fetch 回傳自己判斷後綴空位（2026-07-28 實測）

**可以精確判斷。** fetch 回傳的每條詞綴物件裡，`mods[].tier` 的**開頭字母就是詞綴類型**：

- `P1` / `P2` / `P8` … = **前綴（prefix）**
- `S3` / `S6` / `S9` … = **後綴（suffix）**

⚠ **一條顯示文字可能由多條詞綴合成**，所以**要數不重複的 `(name, tier)`，不能數顯示行數**。
實測樣本：

```jsonc
{ "description": "+167 to maximum Life",
  "mods": [ {"name": "Urchin's", "tier": "P2"},    // 複合前綴（同時給護甲）
            {"name": "Fecund",   "tier": "P1"} ] } // 純生命前綴
// "Urchin's" 也出現在 '+33 to Armour' 那一行 —— 同一條詞綴、兩行顯示
```

判斷式（稀有裝前綴 3 條、後綴 3 條上限）：

```
native_suffixes = 不重複 (name, tier) 中 tier 以 'S' 開頭、且非 crafted 的數量
可上抗性工藝  ⟺  未腐化 且 native_suffixes <= 2
```

工藝詞綴的辨識（見 [../QUERY.md](../QUERY.md) 的詞綴回傳格式）：`flags.crafted` 或
`domain == "crafted"`，且 hash 走 `crafted.` 命名空間。**已有的工藝後綴是可以抹掉重上的**，
所以它佔的那格要算成「可用」而不是「已滿」。

實測四頂高血頭盔的後綴佔用：Royal Burgonet 1 條（**空 2 格**）、Samnite Helmet 3 條、
Praetor Crown 3 條（前後綴全滿）、Pig-Faced Bascinet 3 條。**空位是有的，但不是多數**，
所以值得當成搜尋條件而不是碰運氣。

### 對應的 crafted stat id（`../references/stats.tsv` 實查）

三類都存在於 `crafted` 群組：

| 類型 | id |
|---|---|
| 單元素 | `crafted.stat_3372524247`（火）`crafted.stat_4220027924`（冰）`crafted.stat_1671376347`（雷） |
| 雙元素 | `crafted.stat_2915988346`（火冰）`crafted.stat_3441501978`（火雷）`crafted.stat_4277795662`（冰雷） |
| 元素＋混沌 | `crafted.stat_378817135`（火混）`crafted.stat_3393628375`（冰混）`crafted.stat_3465022881`（雷混） |

另外 `crafted.stat_2901986750` = `+#% to all Elemental Resistances` 也存在於 crafted 群組，
但**使用者沒提到它、數值上限也未實測**，先不要拿它估值。

## 對配裝求解器的意義（尚未實作）

現行 [`../../scripts/gear_combo_optimizer_poe1.py`](../../scripts/gear_combo_optimizer_poe1.py)
**只計算裝備身上現有的抗性**，等於系統性低估了「空後綴」裝備的真實價值——
而那正是最便宜的一批。要吃到這個紅利，作法是把每件**未腐化且後綴未滿**的候選
**展開成多個虛擬候選**（不工藝／工藝火 35／冰 35／雷 35／火冰 20+20／火雷 20+20／冰雷 20+20…），
讓求解器自己挑要補哪一種。展開後候選數約 ×7，但 Pareto 剪枝與 `POE_FAST` 都吃得下。

搜尋端同時要調整：這類物件要用「**高生命 + 低抗性 + 未腐化 + count(空後綴|工藝後綴)**」去撈
（見本檔上方的 count 群組寫法）。現有的 `*_maxlife` 池子其實已經偏向這種貨，
只是既沒加 count 過濾、也沒給它工藝加分。

## ❓ 待確認

- ~~一件裝備能同時存在幾條工藝詞綴？~~ **已確認（使用者，2026-07-28）：正常情況下只有一條。**
  所以估值就是「一件最多加一條工藝抗性」，展開模型照這個算。
- 各部位工藝上限是否隨物品等級／基底不同而變（目前照使用者給的表，未逐項實測）。
