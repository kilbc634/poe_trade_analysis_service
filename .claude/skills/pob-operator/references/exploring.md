# 怎麼自己找出沒記載的用法

`api.md` 只收了實際用過的東西，**遠遠不是全部**——光 `mainOutput` 就有 740 個欄位。
需要沒記載的功能時，用下面的手法自己挖，挖到了**寫回 `api.md`**。

底氣來源：**使用者的安裝目錄就是完整的 Lua 原始碼**，沒有編譯、沒有混淆，
而且執行中的所有物件都能即時列舉。

```bash
P="$APPDATA/Path of Building Community"
```

---

## 三種手法，按順序試

| 手法 | 什麼時候用 | 成本 |
|---|---|---|
| **1. runtime 列舉** | 「有沒有某個欄位／方法？」 | 最低，開機後隨便查 |
| **2. grep 原始碼** | 「這個數字怎麼算出來的？」「設定變數叫什麼？」 | 低 |
| **3. 差分比對** | 「改了 X 會影響什麼？」「這個效果反映在哪個欄位？」 | 中，要跑兩次計算 |

---

## 安裝目錄地圖

| 路徑 | 內容 |
|---|---|
| `Modules/Calc*.lua` | 計算引擎。`CalcOffence`（傷害）、`CalcDefence`（防禦）、`CalcTriggers`（觸發）、`CalcPerform`（保留、buff）、`CalcSetup`（環境組裝） |
| `Modules/BuildDisplayStats.lua` | **GUI 側邊欄的標籤 → output 欄位名** |
| `Modules/CalcSections.lua` | **Calcs 分頁的標籤 → output 欄位名 + breakdown 名** |
| `Modules/ConfigOptions.lua` | 所有設定項的 `var` 名與作用 |
| `Modules/ModParser.lua` | 詞綴文字怎麼被解析成 mod |
| `Classes/*.lua` | 各分頁的行為（`SkillsTab`、`ItemsTab`、`TreeTab`、`ImportTab`…） |
| `Data/Skills/*.lua` | 每個技能的完整定義：`skillTypes`、`parts`、`preDamageFunc`、`statMap` |
| `Data/Uniques/*.lua`、`Data/ModCache.lua` | 物品與詞綴資料 |

---

## Recipe 1：從 GUI 上看到的東西反查欄位名

**最常見的需求**——使用者說「我要那個 Effective Hit Pool」，你要知道它叫什麼。

```bash
grep -rn "Effective Hit Pool" "$P/Modules/BuildDisplayStats.lua" "$P/Modules/CalcSections.lua"
```

```
BuildDisplayStats.lua:106: { stat = "TotalEHP", label = "Effective Hit Pool", ... }
CalcSections.lua:2291:     { label = "Effective Hit Pool",{ format = "{0:output:TotalEHP}", ... }
```

→ 欄位是 `output.TotalEHP`。`CalcSections.lua` 還會順便告訴你 breakdown 的名字。

反過來也行：知道欄位名想確認它在 GUI 上叫什麼，grep 欄位名即可。

---

## Recipe 2：runtime 列舉

**找欄位**（`mainOutput` 有 740 個，用關鍵字篩）：

```python
p.eval(r"""
local hits = {}
for k, v in pairs(build.calcsTab.mainOutput) do
  if k:lower():find("reserv") and type(v) ~= "table" then
    hits[#hits+1] = string.format("%-30s %s", k, tostring(v))
  end
end
table.sort(hits)
return table.concat(hits, "\n")
""")
```

實測輸出（會找到 `api.md` 沒收的欄位，例如 `LifeCancellableReservation`）：

```
LifeCancellableReservation     100
LifeReserved                   1587
LifeReservedPercent            43.62
LifeUncancellableReservation   0
LifeUnreserved                 2051
...
```

**找方法**（PoB 的類別把方法放在 metatable 的 `__index`）：

```python
p.eval(r"""
local m = {}
for k, v in pairs(getmetatable(build.skillsTab).__index or {}) do
  if type(v) == "function" then m[#m+1] = k end
end
table.sort(m)
return table.concat(m, ", ")
""")
```

**看某個物件有哪些欄位**（含型別，用來摸索陌生結構）：

```python
p.eval(r"""
local ks = {}
for k, v in pairs(build.calcsTab) do ks[#ks+1] = k .. ":" .. type(v) end
table.sort(ks)
return table.concat(ks, "  ")
""")
```

要結構化資料就 `require("dkjson").encode(...)`，Python 端 `json.loads`。

---

## Recipe 3：差分比對

**問「改了 X 會影響什麼」時最有效**，因為它不需要你事先知道欄位名。

```python
import json
SNAP = ("local t = {} for k,v in pairs(build.calcsTab.mainOutput) do "
        "if type(v)=='number' then t[k]=v end end return require('dkjson').encode(t)")

before = json.loads(p.eval(SNAP))
p.eval("...改動...; build.buildFlag = true; runCallback('OnFrame')")
after = json.loads(p.eval(SNAP))

diff = [(k, before[k], after[k]) for k in before if k in after and before[k] != after[k]]
diff.sort(key=lambda r: -abs((r[2] - r[1]) / (abs(r[1]) or 1)))   # 依相對變化排序
```

實測（關掉 Arrogance Support）→ 54 個欄位變動，排序後第一眼就看得出重點：

```
ManaUnreservedPercent      8.992 -> -12.72
ManaUnreserved                99 -> -140
LifeReserved                1587 -> 0
LifeReservedPercent        43.62 -> 0
ChaosManaEffectiveLife      2051 -> 3638
```

**這也是找「是誰造成某個效果」的最快辦法**：把嫌疑寶石／裝備逐一停用重算，
看哪一次讓目標欄位歸零。保留量就是這樣查出來的——它不會標在個別技能的
`skillData` 上，只能用差分反推。

---

## Recipe 4：找設定變數

```bash
grep -n 'var = "' "$P/Modules/ConfigOptions.lua" | grep -i "overlap\|projectile"
```

每一項的結構是 `{ var = "...", type = "count"/"check", label = "...", ifSkill = "...", apply = function ... }`，
`label` 就是 GUI 上顯示的文字，`apply` 說明它實際加了什麼 mod。

**做技能比較前一定要掃一次有沒有相關設定**——很多「打到幾次」是設定值不是算出來的，
而且預設偏保守，不檢查等於在比不同的假設。

---

## Recipe 5：查某個技能的實際算法

```bash
n=$(grep -n 'name = "Tornado Shot"' "$P/Data/Skills/act_dex.lua" | head -1 | cut -d: -f1)
sed -n "$((n-3)),$((n+60))p" "$P/Data/Skills/act_dex.lua"
```

要看的重點：

- `skillTypes` —— 決定能不能被觸發（`SkillType.Triggerable`）、能不能上圖騰等
- `parts` —— 有幾個計算模式，名稱是什麼
- `preDamageFunc` —— **特殊倍率都寫在這裡**，例如 Tornado Shot 的次要投射物、
  Explosive Arrow 的引信數
- `statMap` / `constantStats` —— 技能自帶的隱藏數值

技能檔依職業分：`act_dex.lua`、`act_str.lua`、`act_int.lua`、`sup_*.lua`（輔助）、
`other.lua`。不確定在哪就 `grep -rn 'name = "技能名"' "$P/Data/Skills/"`。

---

## Recipe 6：查某個機制怎麼實作

直接搜關鍵字，PoB 的命名相當直白：

```bash
grep -rn -i "manaforged" "$P/Modules/" "$P/Data/Skills/"
```

找到後往上下看幾十行通常就懂了。`Modules/CalcTriggers.lua` 的觸發速率、
`Modules/CalcPerform.lua` 的保留與 buff、`Modules/CalcOffence.lua` 的傷害組裝，
都是這樣讀出來的。

---

## 上游資源（本機沒有）

這個設計不 clone PoB 的原始碼 repo，所以以下要上網查
（<https://github.com/PathOfBuildingCommunity/PathOfBuilding>）：

| 路徑 | 為什麼有用 |
|---|---|
| `spec/System/*_spec.lua` | **官方自己寫的 API 用例**，約 30 個檔案，是最接近文件的東西 |
| `.github/workflows/test.yml` | 正確的 `LUA_PATH` 與啟動方式 |
| `docs/rundown.md` | 每個檔案的用途一句話；headless 的唯一官方說明也在這裡 |
| `docs/calcOffence.md`、`docs/modSyntax.md` | 傷害計算與詞綴語法的概念說明 |

安裝目錄裡有的（`Modules/`、`Classes/`、`Data/`）就別上網了，本機的更快也更準
——**版本一定對得上**。

---

## 挖到之後

**寫回 `api.md`。** 這個 skill 的價值就是累積這些，下次不用重挖。

寫的時候標清楚：驗證日期、PoB 版本，以及**是實測還是讀碼推論**——
兩者可信度不同，後者踩過坑（例如 `NewFileSearch` 的時間戳語意，讀碼看起來對，
實跑才發現 `.zip` 也走同一個函式）。
