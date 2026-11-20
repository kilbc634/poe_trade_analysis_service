# PoB 內部 API 速查

> 全部是讀原始碼確認的，**官方沒有文件**。實測於 PoB **v2.67.2** / POE1 3.29。
>
> **這份是隨用隨長的，不是完整參考**——光 `mainOutput` 就有 740 個欄位，
> 這裡收的遠不到零頭。查不到要的東西是正常的，用
> [`exploring.md`](exploring.md) 的手法自己挖，**挖到了寫回這裡**。

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

實測 `calcsEnv` 可能落後一個 frame。**跑通的重建方式（2026-11-16，v2.67.2）**是呼叫分頁自己的
`BuildOutput()`，而且可以順便指定要看哪一條連線、連線裡的哪個技能（不必改主技能）：

```lua
local ct = build.calcsTab
ct.input.skill_number = idx                         -- socketGroupList 的索引
local sg = build.skillsTab.socketGroupList[idx]
sg.mainActiveSkillCalcs = k                         -- 連線內第幾個主動技能（displaySkillList 的索引）
build.buildFlag = true; runCallback("OnFrame")
ct:BuildOutput()
local o  = ct.calcsEnv.player.output
local bd = ct.calcsEnv.player.breakdown             -- 例：bd.MainHand.ShockDPS（字串陣列，結果行以 "= " 開頭）
```

（`build.calcsTab.calcs.buildOutput(build, "CALCS")` 那條路之前沒跑通，不用再試。）

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

---

## 星團珠寶

天賦排位由 `notableSortOrder` 決定（升冪對應軌道索引），以及程式化建立／裝備／配點／存檔
的完整流程 → [`cluster-jewels.md`](cluster-jewels.md)

三個最容易踩的坑先講：`GetSocketedJewel` 讀的是 `build.spec.jewels[nodeId]` 而不是
`itemsTab.slots`；`subGraphs` 的 key 是產生的 nodeId 不是插槽 nodeId；
群組 enchant 有兩行時**兩行都要寫**，否則 `clusterJewelValid` 是 nil。


---

## 換裝備：用物品原文（raw text）建物件，再指派到插槽

實測 2026-09-05（PoB v2.67.2）。`Item` 的建構子直接吃**遊戲裡 Ctrl+C 的那種物品文字**，
所以最省事的路徑是：把交易站 fetch 回來的欄位組回一段 raw，丟給 `new("Item", raw)`。

> ⚠ **建構子的寫法會隨 PoB 更新改變（2026-11-21 實測）。** PoB 自動更新後，`new("Item", raw)` 會丟
> `Extra argument passed to new() during creation of class Item`，新寫法是 **`new("Item"):Item(raw)`**
> （PoB 自己的 `Classes/ItemListControl.lua`、`CompareTab.lua` 都是這樣呼叫的）。
> 要兩個版本都能跑就包一層：
> ```lua
> local ok, ni = pcall(new, "Item", raw)
> if not ok then ni = new("Item"):Item(raw) end
> ```
> 同一類錯誤再出現時，直接 grep 安裝目錄的 `Classes/*.lua` 看 PoB 自己怎麼建那個類別，比猜快。

```lua
local it = build.itemsTab
local ni = new("Item", [==[
Rarity: RARE
Woe Trail
Murder Boots
Item Level: 83
Quality: 20
Implicits: 0
+117 to maximum Life
+34% to Chaos Resistance
30% increased Movement Speed
{crafted}+15% to Cold and Chaos Resistances
]==])
if not ni.base then return "NO BASE" end      -- 底基名打錯就是 nil，一定要檢查
ni:NormaliseQuality(); ni:BuildModList()
it:AddItem(ni, true)                          -- true = noAutoEquip
it.slots["Boots"].selItemId = ni.id
if it.activeItemSet and it.activeItemSet["Boots"] then
    it.activeItemSet["Boots"].selItemId = ni.id
end
it:PopulateSlots(); build.buildFlag = true
```

要點：

- **raw 用 Lua 長字串 `[==[ ... ]==]` 包**，避開跳脫地獄（同 `pob.py:load_build`）。
- **格式**：`Rarity:` → 名字 → **底基名** → `Item Level:` / `Quality:`（可省）→
  `Implicits: N` → N 行隱性 → 其餘詞綴。**`Implicits:` 那個數字是「行數」不是「詞綴數」**，
  一條顯示成兩行的詞綴要算兩行。
- **工藝詞綴前面加 `{crafted}`**。想模擬「買回來自己上工藝」就直接多寫一行。
- 只想算數值時，**把隱性當成一般詞綴、`Implicits: 0`** 也不影響總量——差別只在 UI 分類。
- **`AddItem(item, true)` 之後一定要自己指派插槽**；傳 `false` 會自動裝到第一個空的合法插槽，
  雙戒這種要指定左右手的情況不能用。
- 插槽名就是 XML `<Slot name=...>` 那些字串：`Boots` / `Gloves` / `Body Armour` /
  `Helmet` / `Ring 1` / `Ring 2` / `Amulet` / `Belt` / `Weapon 1` / `Weapon 2`。
- `it:AddDisplayItem()` / `it:CreateDisplayItemFromRaw()` 也能用，但前者會清掉 `displayItem`，
  拿不到 `id`，反而要多繞一圈。上面這條路徑直接握有 `ni.id`。
- **全程沒有存檔**，`build` 只在記憶體裡改。要保住使用者的 build 就別呼叫任何 save。

## 抗性缺口與「還差多少」：`Missing*Resist`

`mainOutput` 直接有算好的缺口，不用自己拿 75 去減（也就不會踩到最大抗性被改過的坑）：

| 欄位 | 意義 |
|---|---|
| `MissingFireResist` / `MissingColdResist` / `MissingLightningResist` / `MissingChaosResist` | 距離**該抗性上限**還差幾點 |
| `FireResistOver75` 等 | 超過 75 的部分（判斷最大抗性有沒有被拉高：沒被拉高時滿抗的 `Missing` 是 0） |
| `FireResistTotal` / `ChaosResistTotal` | 未截頂的總值 |
| `TotemFireResist` 等 | 圖騰的另一套，別拿錯 |

⚠ **`FireResistMax` 這種欄位不存在**（回 `nil`）。想確認最大抗性用 `FireResistOver75`
或直接看 `Missing*Resist` 在滿抗時是不是 0。

## 驗證「有條件的天賦大師」有沒有生效：對照法，不要找 flag

天賦大師常帶條件（例：Life Mastery「**胸甲上沒有 Life 詞綴時** +15% 最大生命」）。
去猜 `modDB:Flag()` 的條件名很容易撲空（`Condition:NoLifeModsOnBodyArmour` 就不存在）。
**可靠的做法是跑兩次比差值**：

```
A：穿上要驗的胸甲          → Life 4183, Spec:LifeInc 106
B：同一件多一條 +100 生命  → Life 4079, Spec:LifeInc 91     ← 掉 15
```

`Spec:LifeInc` 是**天賦樹提供的 %increased Life 總和**，條件不成立時會直接少掉那 15，
比讀任何 flag 都直接。上例還順便量到：那條 `+100 to maximum Life` 是**淨損 104 血**。

同樣手法可以驗任何條件式加成——**改一個變因、跑兩次、比 `mainOutput`**，
比在原始碼裡找條件名快也準（見 [`exploring.md`](exploring.md) 的差分比對）。

## 寶石品質的隱藏來源：插槽顏色相符 +10%（實測 2026-11-11，PoB v2.67.2）

`SkillsTab:UpdateSocketGroups()` 會替「連線有指定 `slot`、該插槽有裝備、且寶石顏色與對應插槽顏色相同」
的寶石設 `gemInstance.matchesSocket = true`，計算時品質 **+10**（`data.misc.MatchingSocketQualityBonus`）。

- 連線沒指定 `slot`、或插槽沒裝備 → **沒有這 10%**。空白 build 量品質類效果時要先決定要不要算它，否則前後對照會差 10。
- 用 raw 建的測試裝沒寫 `Sockets:` 時，PoB 給的預設插槽顏色不一定跟寶石相符（實測紅色輔助吃到、藍色主動技能沒吃到）。要精準就自己寫 `Sockets: B-R-...`。
- 讀實際生效品質：`mainSkill.effectList[i].quality`（`srcInstance.quality` 是寶石本身的品質）。
- 「Socketed Skill Gems」類詞綴只作用於主動技能寶石；「all Skill Gems」（Ashes of the Stars）也不加輔助。

---

以下各節實測 2026-11-15～17，PoB v2.67.2。使用情境是「拿別人的 build 當範本，換成使用者的裝備與條件」，
整個流程見 `poe-build-upgrade` skill。

## 天賦樹上的珠寶：清除與插入都要動 `spec.jewels`

天賦樹珠寶的插槽也在 `itemsTab.slots` 裡（有 `slot.nodeId` 的那些），但**真正生效的是
`build.spec.jewels[nodeId]`**。只把 `slot.selItemId` 設成 0，畫面上的欄位清了，珠寶還在算。
實際踩過：範本作者的四顆珠寶（含一顆星團）因此留在兩個版本的結果裡。

```lua
-- 清空全部
local it, spec = build.itemsTab, build.spec
for name, slot in pairs(it.slots) do
  if slot.nodeId then
    slot:SetSelItemId(0)
    spec.jewels[slot.nodeId] = 0
    if it.activeItemSet and it.activeItemSet[name] then it.activeItemSet[name].selItemId = 0 end
  end
end
for nodeId in pairs(spec.jewels) do spec.jewels[nodeId] = 0 end
spec:BuildClusterJewelGraphs()        -- 星團長出來的節點要靠這個收掉
spec:BuildAllDependsAndPaths()
it:PopulateSlots(); build.buildFlag = true; runCallback("OnFrame")
-- 一定要回頭數：spec.jewels 裡非 0 的、以及有 nodeId 而 selItemId ~= 0 的插槽，兩者都要是 0
```

插入一顆：照「換裝備」那節建物件之後，`slot:SetSelItemId(ni.id)` 加上 `spec.jewels[slot.nodeId] = ni.id`。
插槽節點本身要已經配點（`spec.nodes[slot.nodeId].alloc`），否則不生效。
星團被清掉之後，原本花在星團裡的點數會空出來，總點數要重新對。

## 匯入公開角色（官網的 character-window）

無頭模式沒有 PoB 自己的下載函式，所以由外面抓三個端點，再交給匯入分頁：

| 端點（`https://www.pathofexile.com/character-window/…`） | 參數 |
|---|---|
| `get-characters` | `accountName`（含 `#` 數字尾碼）、`realm=pc` |
| `get-passive-skills` | 另加 `character` |
| `get-items` | 另加 `character` |

角色公開時不需要 cookie。User-Agent 照專案規矩從 `.poe_cookies.json` 讀，不要寫死；請求之間留間隔。

```lua
local dkjson = require "dkjson"
local tab = build.importTab
pas.bandit_choice = pas.bandit_choice or build.configTab.input.bandit or "None"   -- 官網不回傳盜賊選擇
local cd = copyTable(char); cd.passives = pas; cd.jewels = pas.items
tab:ImportPassiveTreeAndJewels(cd, true)
local cd2 = copyTable(char); cd2.equipment = itm.items; cd2.guardian = itm.guardian
tab:ImportItemsAndSkills(cd2, true, true, true)
```

- **盜賊、萬神殿、設定頁的一切都不會匯入**。盜賊要問使用者（預設值不能當真，實際踩過：假設幫 Alira，使用者是全殺）。
  先 `load_build` 一份已經設好的檔再匯入，就能保留設定頁。
- 存檔：`build:SaveDB("code")` 回傳 XML 字串，自己寫到檔案。
- 使用者之後在 GUI 裡調過的檔是**他的**，只讀不寫；要試東西就在記憶體裡改，或另存新檔名。

## 感電效果：設定頁那格是手填的，PoB 不會自己算

`build.configTab.input.conditionShockEffect` 是使用者打的數字。PoB 計算頁有「依敵人閾值的感電效果」表，
算式在 `Modules/CalcOffence.lua`（約 5210～5233 行）：

```
效果 = 50 × (感電傷害 ÷ 敵人異常閾值)^0.4 × 感電效果加成      （上限 output.MaximumShock）
```

- 感電傷害：上一節的方式切到「真正負責上感電的那條連線」，讀 `breakdown.MainHand.ShockDPS` 的結果行。
  負責上感電的不一定是主技能（實例：魔改箭矢觸發的 Lightning Arrow 配 Overcharge）。
- 敵人閾值：`data.monsterAilmentThresholdTable[enemyLevel]` × 頭目 7.68 × `mapLevelBossLifeMult` ×
  `mapLevelBossAilmentMult` × `enemyDB:More(nil,"Life")` × `enemyDB:More(nil,"AilmentThreshold")`。
  設定頁選巔峰頭目（Pinnacle）時實算 6,349,995。
- 感電效果加成：`output.MainHand.ShockEffectMod`。
- **算出來的值會被目前填的值影響**（被感電的敵人受到更多傷害，感電傷害跟著變）。
  要把結果填回去重算，重複到不變為止；從一個低的起點（例如 15）開始，實測幾輪內就收斂（迴圈上限設 8 就夠）。
- 驗證過：作者影片裡口述的 44%，用這個算法在他的原檔上重現為 44.4%。

## 雜項

- **`CombinedDPS` 對 `TotalDPS`**：有幻影射手（Mirage Archer）這類分身時，`TotalDPS` 只有本體，
  `CombinedDPS` 才是合計，兩者可以差到一倍。比較昇華或輔助寶石時用錯指標會量到「沒有效果」。
- **PoB 沒模擬的效果會量到「完全沒變」**：例如 Barrage of Volley Fire 的品質（每 5% 讓首尾兩發多 1 個投射物）。
  量到零差異時去看寶石或物品的實際敘述，不要直接下結論。
- **傳奇的數值範圍**：物品詞綴帶 `(a-b)` 時由該行的 `range`（0～1）決定取值。
  要算特定數值就在 raw 裡直接寫死數字，最不會出錯。
- **藥劑開關**：`build.itemsTab.slots["Flask 1"].active = true/false`，改完重算。
  量一瓶藥劑的價值時只切這一瓶，並且要試「它取代哪一瓶」。
- **天賦專精**：專精節點的選項記在 `spec.masterySelections[node.id] = effectId`，設完要
  `spec.tree:ProcessStats(node)` 再 `AllocNode`，否則節點點了但沒有效果。
- **只配指定的昇華大點**：先 `DeallocNode` 不要的大點、`BuildAllDependsAndPaths()`，再 `AllocNode` 要的，路徑小點會自動補。
- **依點數修剪天賦樹**：候選是 `#node.depends == 1` 的葉節點（排除專精、珠寶插槽、起點），
  每次拿掉「損失最少」的一個。要另外設保護條件（生命、屬性、壓制不得下降），否則會先砍掉防禦。
- **Lua 語法陷阱**：`t[[==[key]==]]` 會被解析成長字串的開頭而報錯，要寫成 `t[ [==[key]==] ]`（中括號後留空格）。
- **設定頁改值**：`build.configTab.input[key] = v` 之後要 `build.configTab:BuildModList()` 才會生效。
- **角色等級**：`build.characterLevel = n; build.characterLevelAutoMode = false; build.configTab:UpdateLevel()`。
