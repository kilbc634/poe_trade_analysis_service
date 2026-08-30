# PoB 內部 API 速查

> 全部是讀原始碼確認的，**官方沒有文件**。實測於 PoB **v2.67.2** / POE1 3.29。
> 要查沒記載的東西，直接 grep 使用者的安裝目錄——那就是完整原始碼。

`p.eval(chunk)` 執行一段 Lua，`return` 的東西會被轉成字串傳回 Python。
要結構化資料就在 Lua 裡 `require("dkjson").encode(...)`，Python 端再 `json.loads`。

---

## 物件樹

```
build                       ← 全域，HeadlessWrapper 設好的
├── characterLevel
├── buildName
├── mainSocketGroup         ← 目前選中的連線（1-based index）
├── spec.curClassName
├── skillsTab.socketGroupList[i]
│   ├── slot                ← "Body Armour" / "Gloves" / "Weapon 1" …
│   ├── displayLabel
│   ├── enabled
│   ├── includeInFullDPS
│   ├── mainActiveSkill     ← 連線內選第幾個主動技能
│   ├── gemList[j]          ← 見下
│   └── displaySkillList[k] ← 計算後才有
├── itemsTab / treeTab / configTab / importTab / notesTab
├── calcsTab
│   ├── mainOutput          ← 主要輸出（build 載入前是 nil）
│   ├── mainEnv             ← 計算環境
│   ├── calcsEnv / calcsOutput   ← CALCS 模式，含 breakdown，但可能落後一個 frame
│   └── calcs               ← 計算模組本身
└── data                    ← 遊戲資料（寶石、技能、獨特物…）
```

---

## 讀輸出

```lua
local o = build.calcsTab.mainOutput
```

常用欄位（`mainOutput` 有數百個，這裡只列驗證過的）：

| 欄位 | 意義 |
|---|---|
| `TotalDPS` | 主技能 DPS |
| `CombinedDPS` / `FullDPS` | 合計 / 全技能合計（`FullDPS` 需要各連線開 `includeInFullDPS`） |
| `AverageDamage` | 單次命中平均傷害 |
| `Speed` / `HitSpeed` | 每秒出手 |
| `ManaCost` / `ManaCostRaw` | 法力消耗 |
| `Cooldown` | 冷卻 |
| `SkillTriggerRate` / `ServerTriggerRate` / `SourceTriggerRate` / `EffectiveSourceRate` | 觸發技能的速率 |
| `Life` / `Mana` / `EnergyShield` | 上限值 |
| `LifeReserved` / `LifeReservedPercent` / `LifeUnreserved` / `LifeUnreservedPercent` | 生命保留 |
| `ManaReserved` / `ManaReservedPercent` / `ManaUnreserved` / `ManaUnreservedPercent` | 法力保留 |
| `TotalEHP` | 有效生命 |
| `CritChance` / `CritMultiplier` | 暴擊 |

**關鍵公式**（`Modules/CalcOffence.lua:3712`）：

```
TotalDPS = AverageDamage × (HitSpeed or Speed) × skillData.dpsMultiplier × quantityMultiplier
```

所以「**單次施放對單一目標的總傷害**」＝ `AverageDamage × dpsMultiplier × quantityMultiplier`
——這個度量把觸發頻率與冷卻除掉，同時保留多重命中。

`dpsMultiplier` 取自 `build.calcsTab.mainEnv.player.mainSkill.skillData.dpsMultiplier`。

---

## 換寶石

```lua
local sg = build.skillsTab.socketGroupList[5]
local gem = sg.gemList[2]
gem.gemId, gem.skillId, gem.gemData, gem.grantedEffect = nil   -- 清掉舊的
gem.nameSpec = "Tornado Shot"
build.skillsTab:ProcessSocketGroup(sg)                          -- 依名稱重新解析
build.buildFlag = true ; runCallback("OnFrame")                 -- 重算
```

整條重建：

```lua
sg.gemList = {}
table.insert(sg.gemList, {nameSpec = "Manaforged Arrows", level = 20, quality = 20,
                          enabled = true, new = true, enableGlobal1 = true})
-- …其餘寶石…
build.skillsTab:ProcessSocketGroup(sg)
```

**`ProcessSocketGroup` 會自動把等級壓回 `gemData.naturalMaxLevel`**，所以塞
`level = 20` 只是初始值：Invert the Rules / Enhance / Eclipse 會變 3，
Empower 與覺醒系會變 4~5。不必自己判斷。

解析失敗時 `gem.errMsg` 有值（`Unrecognised gem name` / `Ambiguous gem name`）。
名稱比對很寬鬆（`SkillsTab:FindSkillGem` 支援縮寫），但**寫全名最保險**。

---

## 選連線內的技能與 skill part

一條連線可能有多個主動技能，很多技能還有 part（例如 Tornado Shot 的
`Single Projectile` / `Combined Average Projectiles`）：

```lua
build.mainSocketGroup = 5
local sg = build.skillsTab.socketGroupList[5]
sg.mainActiveSkill = 2                         -- displaySkillList 的 index
build.buildFlag = true ; runCallback("OnFrame")

local ds = sg.displaySkillList[sg.mainActiveSkill]
ds.activeEffect.srcInstance.skillPart = 2      -- 選 part
build.buildFlag = true ; runCallback("OnFrame")
```

part 數量：`skill.activeEffect.grantedEffect.parts` 的長度；名稱在 `parts[i].name`。

**part 選錯數字會差很多。** 例：Tornado Shot part 1 的 `dpsMultiplier` 是 1，
part 2 是 7（＝ `1 + 60% × 次要投射物數`）。要比較技能時，**逐一掃過所有 part 取最大**
比猜哪個對可靠。

---

## 改設定（Configuration 分頁）

```lua
build.configTab.input.stormRainBeamOverlap = 5
build.configTab:BuildModList()
build.buildFlag = true ; runCallback("OnFrame")
```

變數名在 `Modules/ConfigOptions.lua` 的 `var = "..."`，直接 grep：

```bash
grep -n 'var = "' "$APPDATA/Path of Building Community/Modules/ConfigOptions.lua"
```

**很多技能的「打到幾次」是設定值，不是算出來的**，而且預設偏保守。做技能比較前
務必檢查有沒有這類設定，否則等於在比不同的假設。已知的重疊類設定：
`stormRainBeamOverlap`、`toxicRainPodOverlap`、`ShrapnelBallistaProjectileOverlap`、
`perforateSpikeOverlap`、`tornadoShotSecondaryHitChance`、`enemyRadius`。

---

## 觸發技能

```lua
local skill = build.calcsTab.mainEnv.player.mainSkill
skill.skillData.triggeredByManaforged   -- true = 被魔改箭矢觸發
skill.skillData.triggered               -- 其他觸發來源
```

**用 PoB 的旗標判斷某技能能不能被某個觸發輔助支援**，比自己讀規則可靠——
它已經處理了 `skillTypes` 的 `Triggerable`、圖騰、引導技等所有條件。

---

## 從遊戲資料列舉寶石

```lua
for gemId, gd in pairs(build.data.gems) do
  local t = gd.tags or {}          -- attack / bow / support / grants_active_skill / …
  local ge = gd.grantedEffect
  ge.skillTypes                    -- SkillType.Attack、SkillType.Triggerable、…
  ge.excludeSkillTypes             -- 陣列，值是 SkillType 數字
  ge.requireSkillTypes
  gd.naturalMaxLevel
end
```

`SkillType` 是全域表，`SkillType.Triggered` == 37。

**判斷輔助有沒有「無法輔助觸發攻擊」**：`excludeSkillTypes` 裡含 `SkillType.Triggered`。

小心 **混合寶石**：`tags` 同時有 `support` 與 `grants_active_skill` 的（例如 Voidstorm）
既是輔助又自帶主動技能——量「輔助倍率」時它的增益其實來自自己的技能傷害，
會嚴重高估。列舉輔助時要排除。

---

## 生命 / 法力保留

保留量不會標在個別技能的 `skillData` 上，只能從 `mainOutput` 讀總量。
要知道**是誰造成的**，最快的辦法是關掉某顆寶石重算對照：

```lua
for _, sg in ipairs(build.skillsTab.socketGroupList) do
  for _, g in ipairs(sg.gemList or {}) do
    if g.nameSpec == "Arrogance" then g.enabled = false end
  end
end
build.skillsTab:ProcessSocketGroup(build.skillsTab.socketGroupList[5])
build.buildFlag = true ; runCallback("OnFrame")
```

（`Arrogance Support` 會把法力保留轉成生命保留，是生命保留最常見的來源。）

---

## breakdown（逐行算式）

`mainOutput` 只有結果；PoB 內部還有一份逐行算式，但**只在 CALCS 模式產生**：

```lua
build.calcsTab.calcsEnv.player.breakdown.SkillTriggerRate   -- 字串陣列
```

實測 `calcsEnv` 可能落後一個 frame。要強制重建可以試
`build.calcsTab.calcs.buildOutput(build, "CALCS")`（本 session 未跑通，若要用需自行排查）。

---

## 已知的計算細節

**魔改箭矢的觸發速率是階梯式量化的**（`Modules/CalcTriggers.lua:521-548`）：

```lua
local manaSpentThreshold = triggeredManaCost * ManaForgedArrowsPercentThreshold  -- ×3
trigRate = trigRate / m_ceil(manaSpentThreshold / sourceManaCost)
```

那個 `ceil()` 表示 driver 出手次數必須湊整數，所以 payload 的法力消耗只在
邊界翻轉時才影響觸發率——「成本 +5%、觸發率 −33%」這種懸崖是常態。
payload 消耗為 0 時整段被跳過（`if triggeredManaCost > 0` 不成立）。

**堆疊型技能的數字不是單次觸發**：Explosive Arrow 的「引信數」是由持續攻速推出來的，
Lightning Arrow of Electrocution 的 `dpsMultiplier` 來自層數倍率。拿來跟單發技能比會嚴重失真。

---

## 除錯

**開機失敗**

| 訊息 | 原因 |
|---|---|
| `module 'xml' not found` | `package.path` 沒含安裝目錄的 `lua/` |
| `attempt to index global 'arg'` | 沒設 `arg = {}` |
| `unexpected symbol near '#'` | `headless_boot.lua` 第一行不是 `#@`（產生器塞了檔頭進去） |
| `Missing LUT: <珠寶名>` | 永恆珠寶快取沒建好，重跑 `pob.py` 讓它補 |

以上 `pob.py` / `make_boot.py` 都已處理，出現代表產生器或路徑被改壞了。

**數字對不上 GUI**：先確認版本一致（`install_version()`），再確認你沒有不小心改掉
其他連線——例如重建某條連線時洗掉了 Sniper's Mark 這種全域增傷，整個 build 的
數字都會跟著掉。

**存取違規（access violation）**：多半是 ctypes 綁定寫錯。已知一個：
`lua_tolstring` 的 `restype` **必須是 `c_void_p` 而不是 `c_char_p`**——後者會把回傳值
轉成 bytes 並在第一個 NUL 截斷，處理壓縮資料時就會讀出界。
