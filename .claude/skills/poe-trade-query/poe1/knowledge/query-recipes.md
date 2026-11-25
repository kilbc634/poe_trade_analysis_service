> ⛔ **POE1 ONLY**｜聯盟：**Covens**（3.30）｜實測：**2026-11-20～25**
> 若 `REALM=poe2`，停止並改讀 `../../poe2/`。stat id 一律以 `../references/stats.tsv` 為準，這裡只記「怎麼組」。

# 查詢寫法與回傳欄位的實測筆記

組一整套流派的採買清單時用到、之前沒記過的寫法。每一條都實際送出過。

## 傳奇

- **多基底的傳奇只給 `name`、不給 `type` 也能查**（Precursor's Emblem 有五種戒指基底）。要鎖基底再加 `type`。
- **變異（Foulborn）詞綴就是 `explicit.` 群組的 stat**，直接放進 `and` 群組即可篩出帶特定變異詞的版本；
  另有 `misc_filters.mutated`。回傳的名稱會帶 `Foulborn` 前綴，查詢的 `name` 仍用原名。
- **瓦詞用 `implicit.` 群組**（例：手套的 `+# to Maximum Frenzy Charges`、胸甲的 `+# to Level of Socketed Duration Gems`）。
- **神殿腰帶 Screams of the Desiccated 的各種神殿是各自一個 `explicit.` stat**。
  3.30 把詞綴文字改成「Players have … Shrine Buff」，`stats.tsv` 裡舊文字「You have …」對應的 id 仍然有效。
- **六連**：`socket_filters.links.min = 6`；只要插槽數用 `sockets.min`。
- **寶石**：`type` 用寶石全名（輔助寶石要含 ` Support`），等級與品質在 `misc_filters.gem_level`／`quality`。
  變體寶石（例：Frenzy of Onslaught）用 `term` 查得到。

## 星團珠寶

```jsonc
{ "filters": { "type_filters": { "filters": { "category": { "option": "jewel.cluster" } } } },
  "stats": [ { "type": "and", "filters": [
      { "id": "enchant.stat_3948993189", "value": { "option": 1 } },   // 小天賦種類：option 是 stats.tsv 裡「id|N」的 N
      { "id": "enchant.stat_3086156145", "value": { "max": 8 } },      // 天賦數
      { "id": "explicit.stat_…（1 Added Passive Skill is X）" } ] } ] }
```

- 小天賦種類的 id 在 `stats.tsv` 寫成 `enchant.stat_3948993189|1` 這種形式，查詢時拆成 `id` 與 `value.option`。
- 要「三顆大點裡至少兩顆」用 `count` 群組。
- **大點的排位由資料裡的排序值決定**（見 `pob-operator` 的 cluster-jewels.md）。要卡位就得指定第三顆是哪一個，
  不能只搜前兩顆：同樣帶兩顆目標大點的星團，第三顆不同，價格可以差二十倍，能不能卡位也不同。

## 稀有珠寶的抗性

- **`pseudo.pseudo_total_fire_resistance` 這類分項 pseudo 對 `jewel.base` 回 0 筆**（三項各 ≥15 也是 0）。原因沒有查，可能是寫法問題。
- 可行的寫法是 **`weight` 群組直接用 explicit 的抗性 stat**：全抗權重 3、雙抗權重 2、單抗權重 1，門檻設總點數。
- 稀有珠寶最多兩條抗性後綴，另外兩條可以是傷害詞綴；這種珠寶 1–15c 就有，是補抗性最便宜的部位。
- 珠寶的 `raw` 交給 PoB 前要確認基底名解析得出來（有少數回傳的基底 PoB 不認得）。

## 回傳欄位

- **催化劑品質在 `item.properties`**，名稱是 `Quality (Attack Modifiers)`、`Quality (Life and Mana Modifiers)` 等。
  詞綴的數值**已經含這個品質**。要模擬「買回來上催化劑」時，先排除已有品質的掛單。
  實測一池 495 顆命中戒指裡 34 顆已帶品質，而且因為數值看起來高，排序會排在前面。
- **3.30 的詞綴文字帶標記**，例如 `+17% to [PlayerItemRarity|Item Rarity]`、`[affliction_notable_x|Name]`。
  交給 PoB 或顯示前用 `\[[^\]|]+\|([^\]]+)\]` 取右半邊。
- **Doedre's Elixir 這類範圍詞綴，每件的數值是固定的**（例：`Gain 3 Frenzy Charges on use`），可以直接用 stat 的 `min` 篩。

## 取樣

- 價格遞增只抓前 N 筆會全部落在最便宜的一端（實測一池 30 筆全是 1c）。
  要看得到整條價格階梯，從回傳的 100 個 hash 裡**取前半便宜的＋後段等距取樣**。
- 同時跑兩支會打交易站的程式會撞限流（實測吃到 257 秒）。一次只跑一支，其他工作排在它後面。
