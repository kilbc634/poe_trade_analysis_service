# 星團珠寶：天賦排位機制與程式化操作

> POE1 only ｜實測於 PoB **v2.67.2** / 3.29 ｜最後驗證：**2026-09-05**
>
> 排位規則是讀 `Classes/PassiveSpec.lua` 原始碼推導、再用 PoB 實際建出星團子圖驗證的，
> 兩者吻合。使用者也確認產出的物品與市面上實際販賣的一模一樣。

---

## 1. 核心規則：sortOrder 決定天賦的位置

**巨型星團上關鍵天賦的擺放位置不是隨機的，也不看你在詞綴列的輸入順序**，
而是由 PoB 資料裡的 `notableSortOrder` 決定。

`Classes/PassiveSpec.lua:2039` 起：

```lua
table.sort(notableList, function(a, b) return sortOrder[a.dn] < sortOrder[b.dn] end)
...
table.sort(notableIndexList)          -- 可用的軌道索引，也升冪
...
for index, baseNode in ipairs(notableList) do
    local nodeIndex = notableIndexList[index]   -- 一對一配對
```

兩個列表都升冪、一對一配對 →

> **`notableSortOrder` 數字越小的天賦，落在越小的軌道索引（oidx）。**

`sortOrder` 表在 `Data/ClusterJewels.lua` 的 `notableSortOrder`，共約 300 筆，
涵蓋全樹所有 cluster notable。

```lua
build.data.clusterJewels.notableSortOrder["Arcing Shot"]   --> 11359
```

---

## 2. 最省天賦點的巨型星團（5 點拿 2 關鍵 + 2 珠寶孔）

### 形狀

**8 節點 / 3 關鍵天賦 / 2 珠寶孔**的巨型星團。實測環上長這樣（入口在 oidx 15）：

| oidx | 內容 | 離入口步數 |
|--:|---|--:|
| 15 | 小天賦 ← **入口** | 0 |
| **01** | **關鍵天賦（sortOrder 最小）** | **1（順時針）** |
| 04 | 珠寶孔 | 2 |
| 05 | 小天賦 | 3 |
| 07 | 關鍵天賦（sortOrder 中間） | 4 |
| 08 | 小天賦 | 3（逆） |
| 09 | 珠寶孔 | 2（逆） |
| **12** | **關鍵天賦（sortOrder 最大）** | **1（逆時針）** |

### 手法

**sortOrder 最小與最大的兩顆各離入口 1 步，中間那顆被推到正對面（4 步）。** 所以：

> **要卡位的廢天賦，`sortOrder` 必須排在三顆的「中間」。**

點法：入口(1) → 順時針拿 oidx 01(2) → 珠寶孔 04(3) → 回頭逆時針拿 oidx 12(4) → 珠寶孔 09(5)
= **5 點拿到 2 個要的關鍵天賦 ＋ 2 個中型星團孔**，中間那顆完全不碰。

### 中型與小型不必這樣算

**中型和小型星團不論選幾個關鍵天賦，都必須點到底部**，過路點數固定，
所以排序位置沒有操作空間。深挖 `notableIndicies` 的特殊規則對這兩種尺寸沒有實務價值。

（程式碼裡中型確實有兩套索引替換 —— `socketCount == 0 and notableCount == 2` 時 6→4、10→8；
`nodeCount == 4` 時 10→9、2→3 —— 記在這裡備查，但不影響選擇。）

---

## 3. 查某個群組有哪些 notable

`clusterNodeMap` 上**沒有**群組資訊，要去 `Data/ModJewelCluster.lua`
撈 `weightKey` 含該群組 tag、且對應 `weightVal > 0` 的 `"1 Added Passive Skill is X"` 詞綴。

```python
import io, re
src = io.open(APPDATA + "/Path of Building Community/Data/ModJewelCluster.lua",
              encoding="utf-8").read()
for line in src.split("\n"):
    m = re.search(r'"1 Added Passive Skill is ([^"]+)"', line)
    wk = re.search(r'weightKey = \{([^}]*)\}', line)
    wv = re.search(r'weightVal = \{([^}]*)\}', line)
    if not (m and wk and wv): continue
    keys = [k.strip().strip('"') for k in wk.group(1).split(",") if k.strip()]
    vals = [v.strip() for v in wv.group(1).split(",") if v.strip()]
    if "affliction_bow_damage" not in keys: continue
    w = int(vals[keys.index("affliction_bow_damage")])
    if w > 0: print(m.group(1), w)
```

`weightVal` 就是刷到的權重，可以直接當「多好刷」的依據。
另外 `weightMultiplierKey/Val` 裡的 `expansion_jewel_medium` 若為 0，代表該天賦**只能上巨型**。

**群組 tag → 小天賦文字**在 `Data/ClusterJewels.lua` 的 `jewels[<尺寸>].skills[<tag>]`：

```lua
build.data.clusterJewels.jewels["Large Cluster Jewel"].skills["affliction_bow_damage"].stats
--> { "12% increased Damage with Bows", "12% increased Damage Over Time with Bow Skills" }
```

**注意：星團珠寶群組裡沒有任何一個的小天賦是「暴擊加成」（Critical Strike Multiplier）。**
暴擊加成只散落在個別 notable 上，且無條件的最多只有 +15%（Skullbreaker）。

---

## 4. 尺寸的軌道資料

`Data/ClusterJewels.lua` 的 `jewels[<全名>]`：

| 尺寸 | totalIndicies | notableIndicies | socketIndicies |
|---|--:|---|---|
| Small Cluster Jewel | 6 | `{4}` | `{4}` |
| Medium Cluster Jewel | 12 | `{6,10,2,0}` | `{6}` |
| Large Cluster Jewel | 12 | `{6,4,8,10,2}` | `{4,8,6}` |

**這些索引不是最終的 oidx。** 實際軌道是 `nodeOrbit = sizeIndex + 1`，
巨型是軌道 3、每軌 16 格，所以 `{2,6,10}` 會被展開成實測的 `{1,7,12}`。
**要精確位置就直接建出來讀 `subGraph.nodes[].oidx`**（見下），不要自己換算。

推導流程（巨型 3 notable + 2 孔）：
`socketIndicies` 前 2 個 → 4、8 被吃掉 → `notableIndicies` 依序挑沒被佔用的
→ 6、(4 skip)、(8 skip)、10、2 → 排序 → `{2, 6, 10}` → 展開為 oidx `{1, 7, 12}`。

---

## 5. 程式化建立、裝備、配點

### 物品文字格式

**兩行 enchant 都要寫**（PoB 的 mod key 是 `table.concat(skill.enchant, " "):lower()`，
少一行就認不出群組，`clusterJewelValid` 會是 nil）：

```
Rarity: RARE
Focused Fletching
Large Cluster Jewel
Item Level: 84
Adds 8 Passive Skills
2 Added Passive Skills are Jewel Sockets
Added Small Passive Skills grant: 12% increased Damage with Bows
Added Small Passive Skills grant: 12% increased Damage Over Time with Bow Skills
1 Added Passive Skill is Arcing Shot
1 Added Passive Skill is Tempered Arrowheads
1 Added Passive Skill is Smite the Weak
```

一個孔寫 `Added Passive Skill is a Jewel Socket`，多個孔寫 `N Added Passive Skills are Jewel Sockets`。

驗證有沒有吃進去：

```lua
it.jewelData.clusterJewelValid   -- 非 nil 才會建子圖（實際回傳 nodeCount）
it.jewelData.clusterJewelSkill   -- 群組 tag
it.jewelData.clusterJewelNotables
```

### 裝備到插槽

**關鍵坑：`GetSocketedJewel` 讀的是 `build.spec.jewels[nodeId]`，不是 `itemsTab.slots`。**
只設 `slot.selItemId` 不會建子圖。

```lua
local it = new("Item", raw)
build.itemsTab:AddItem(it, true)
-- 找空的巨型星團孔（expansionJewel.size == 2）
for id in pairs(build.spec.tree.sockets) do
  local nd = build.spec.nodes[id]
  if nd and nd.expansionJewel and nd.expansionJewel.size == 2
     and (not build.spec.jewels[id] or build.spec.jewels[id] == 0) then
    build.spec.jewels[id] = it.id
    break
  end
end
build.spec:BuildClusterJewelGraphs()
build.buildFlag = true ; runCallback("OnFrame")
```

### 讀子圖

**`subGraphs` 的 key 是產生的 nodeId，不是插槽的 nodeId。** 要靠 `parentSocket` 反查：

```lua
for key, sg in pairs(build.spec.subGraphs) do
  sg.parentSocket.id        -- 插槽的 nodeId
  sg.entranceNode.oidx      -- 入口位置
  for _, n in ipairs(sg.nodes) do
    n.oidx, n.type, n.dn    -- type: "Notable" / "Socket" / "Normal" / "Mastery"
  end
end
```

### 配點

`AllocNode` **會自動把整條路徑一起點亮**（走 `node.path`），所以只要對目標節點呼叫：

```lua
build.spec:BuildAllDependsAndPaths()          -- 先算路徑，否則 node.path 是空的
for _, sg in pairs(build.spec.subGraphs) do
  for _, n in ipairs(sg.nodes) do
    if n.dn == "Arcing Shot" or n.dn == "Smite the Weak" or n.type == "Socket" then
      build.spec:AllocNode(n)
    end
  end
end
build.spec:BuildAllDependsAndPaths()
build.buildFlag = true ; runCallback("OnFrame")
build.spec:CountAllocNodes()                  -- 確認點數增量
```

### 存回 build 檔

`PassiveSpec:Load` 裡 `if xml.attrib.nodes then` **優先於 legacy `<URL>`**，
所以改寫 `<Spec nodes="...">` 就能存配點，不必動 URL。

```python
ids = pob.eval('local t={} for id in pairs(build.spec.allocNodes) do t[#t+1]=tostring(id) end return table.concat(t,",")')
src = io.open(BUILD, encoding="utf-8").read()
m = re.search(r'(<Spec nodes=")([^"]*)(")', src)
src = src[:m.start(2)] + ids + src[m.end(2):]
io.open(BUILD, "w", encoding="utf-8").write(src)
```

物品本身寫進 `<Items>` 區段（`<Item id="N">` ＋ 原始文字），
插槽指派寫 `<Sockets>` 裡的 `<Socket nodeId="..." itemId="N"/>`。

**改完一定要重新載入驗證** —— 星團子圖的節點 id 是產生的，
要確認 reload 後 `CountAllocNodes()` 與 DPS 都跟存檔前一致。

---

## 6. 量測 notable 價值的手法

不必真的建星團。把 notable 的效果文字注入一件已裝備的物品，走 PoB 真正的 mod 解析器：

```lua
local sd = table.concat(build.spec.tree.clusterNodeMap[name].sd, "\n")
HOST:ParseRaw(ORIG_RAW .. "\n" .. sd)
build.itemsTab:PopulateSlots(); build.buildFlag = true; runCallback("OnFrame")
-- 量完還原
HOST:ParseRaw(ORIG_RAW)
```

`Item:BuildRaw()` → `ParseRaw()` 的往返實測是**無損的**（raw 完全相同、無未解析、DPS 不變），
所以拿已裝備物品當注入宿主是安全的。

檢查有沒有解析失敗：`modLine.extra` 非空即為未解析的殘餘。

### 這個手法會遇到的條件式陷阱

PoB 對條件式增傷的處理很寬鬆，**有些條件根本沒判定**：

| 文字 | PoB 的處理 |
|---|---|
| `with hits against nearby enemies` | 只當成 `KeywordFlag.Hit`，**完全沒有距離判定、也沒有 config 可關**——會高估 |
| `against Maimed Enemies` | 需要 `conditionEnemyMaimed`，預設關 → 顯示 0% |
| `when on Full Life` | 有正確判定（吃 Lifetap 的 build 永不成立） |
| `against Taunted Enemies` | 需要嘲諷來源，預設 0% |

**量條件式 notable 前先 grep `Modules/ModParser.lua` 看它到底怎麼解析那行。**

---

## 相關

- API 速查 → [`api.md`](api.md)
- 自己挖沒記載的用法 → [`exploring.md`](exploring.md)
