---
name: pob-operator
description: Drive Path of Building (POE1) from code — open a build, swap gems, change items or config, and read back any number PoB computes: DPS, effective HP, life/mana reservation, per-skill damage, trigger rates, crit, resistances. Use whenever a question needs PoB's real maths instead of a website's summary — comparing gem or support setups, sweeping combinations, working out what a build would do after a change, or analysing a poe.ninja character beyond the handful of stats its page shows. It runs the user's own installed PoB, so the numbers match what they see on screen. NOT for prices (poe-trade-query) or popularity/META statistics (poe-ninja-builds).
allowed-tools: Bash(python:*) Bash(py:*) Read Grep Glob Write Edit AskUserQuestion
---

> POE1 only（PoB Community）｜最後實測：**2026-09-05**，PoB **v2.67.2**
> PoB 有 PoE2 版本（`Path of Building Community (PoE2)`），**尚未實測**，本檔不得直接套用。

# 操作 Path of Building

> **命名**：這個 skill 叫 `pob-operator`；它要找的**入口資料夾**叫 `pob-headless`。
> 兩者不同，別搞混。（headless 只是實作方式——不開視窗，直接跑 PoB 的計算引擎。）

用 Python 驅動**使用者本機已安裝的 PoB GUI**，程式化讀取它算出來的任何數值。

不是另一份 PoB，也不是重寫的計算器——載入的就是桌面版自己在跑的那些 Lua 檔案，
**同一套計算引擎**，所以數字與使用者螢幕上看到的一致。

---

## Step 1：先確認入口在哪（每個 session 第一次使用時做）

需要的是一個 `pob-headless` 資料夾（裡面有 `pob.py`）。**依序**找：

1. **記憶**：如果有記過入口路徑，直接用（但仍要確認資料夾還在）。
2. **掃檔案系統**：從當前工作目錄往上、以及它的同層找 `pob-headless`：

   ```bash
   ls -d ./pob-headless ../pob-headless ../../pob-headless 2>/dev/null
   ```

   找到後確認 `pob.py` 與 `headless_boot.lua` 都在。

3. **都找不到 → 問使用者**，用 AskUserQuestion 給兩個選項：
   - 「請幫我安裝 headless」→ 走 [`references/install.md`](references/install.md)
   - 「我已經安裝過了，路徑在……」→ 用他給的路徑

**不要自己猜路徑硬跑**，也不要因為找不到就自作主張安裝——安裝會在使用者磁碟上建資料夾，先問。

確認入口後，之後所有指令都在那個資料夾裡跑：

```bash
cd <入口>/pob-headless && python -c "from pob import PoB; ..."
```

---

## 背景：為什麼這件事做得到

### PoB 的結構

PoB 是 **Lua 程式 + 一顆 C++ host DLL**：

```
Path of Building.exe  →  SimpleGraphic.dll  →  Launch.lua  →  Modules/*.lua
                          （host）              （入口）        （計算引擎）
```

`SimpleGraphic.dll` 名字叫「圖形」，實際上提供了所有 Lua 5.1 做不到的事：繪圖、
檔案系統、剪貼簿、計時、**壓縮**（內嵌 zlib）。Lua 那層只寫邏輯。

### headless 是官方提供的另一個入口

PoB repo 裡有 `src/HeadlessWrapper.lua`（227 行），把 `SimpleGraphic.dll` 換成 Lua 空殼，
然後照樣 `dofile("Launch.lua")`。官方自己的 CI 就用它跑整套 `spec/` 測試。

**這個 skill 的做法**：把（修補過的）wrapper 放在 `pob-headless/`，用 Python ctypes
掛載 PoB 安裝目錄的 `lua51.dll`（LuaJIT 2.1）當直譯器，工作目錄設在安裝目錄，
以絕對路徑載入 wrapper。它的 `dofile("Launch.lua")` 因此抓到 GUI 版自己的入口。

```
pob.py  →  安裝目錄的 lua51.dll  →  headless_boot.lua  →  安裝目錄的 Launch.lua
                                    （在 pob-headless/）    （從這裡開始就是 GUI 版本體）
```

**結果：本機只有一份 PoB，它自動更新後 headless 立刻同步。**

### 不會動到使用者的安裝

`headless_boot.lua` 住在 `pob-headless/`，不放進安裝目錄。唯一的寫入是
`Data/TimelessJewelData/*.bin`（永恆珠寶快取），而那是 GUI 版自己也會產生的檔案。

要驗證安裝沒被破壞，用 PoB 自己的 `manifest.xml`（內含每個檔案的 SHA-1）比對。

---

## 常用操作

```python
from pob import PoB
p = PoB()                        # 開機（約 10~20 秒，載天賦樹與物品資料）

# 三種載入方式
p.load_build(r"C:\...\Documents\Path of Building\Builds\某個build.xml")
p.load_build_code(code)          # poe.ninja / pobb.in / 論壇的 import code
p.eval("newBuild()")             # 空白 build

# 讀值：mainOutput 裡有幾百個欄位
p.eval("return tostring(build.calcsTab.mainOutput.TotalDPS)")

# 改東西 → 一定要 recalc
p.recalc()

code = p.export_code()           # 產生分享碼
```

命令列快速檢查一份 build：

```bash
python pob.py "路徑\某個build.xml"
```

**欄位名、怎麼換寶石、怎麼改設定、怎麼選技能 part** → [`references/api.md`](references/api.md)

### 產出寫哪裡

**跑分析產生的任何東西——腳本、量測 json、報告、log——一律寫進
`<入口>/pob-headless/output/`，不要丟在入口根目錄。** 根目錄只該有
`pob.py`、`make_boot.py`、`headless_boot.lua`、`README.md`、`cache/`、`output/`
（外加 Python 自己產生的 `__pycache__/`）。

在 `output/` 裡跑腳本要 import `pob`，記得把上層加進路徑：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pob import PoB
```

`output/` 可以隨時清空，裡面沒有運作所需的東西。

---

## 一定要知道的坑

**PoB 的資料檔不是詞綴池或權重的來源。** `Data/Mod*.lua` 裡有 `weightKey`／`weightVal`，看起來能拿來算
「這個基底骰到某詞綴的機率」，但它收錄了絕版與實際骰不出來的條目，加總出來的分母是錯的
（實例：Searching Eye Jewel 的後綴總權重，PoB 資料是 47,775，poedb 是 38,875）。
詞綴能不能骰、每一階的物品等級與權重，一律用 `poedb-mods` skill 查，數字有出入時以 poedb 為準。
PoB 只用來算它擅長的事：把已經存在的裝備放上去算數值。

**PoB 的輸出是緩衝的**，Lua 的 `ConPrintf` 會在行程結束時才一次沖出來，
所以終端機上的訊息順序**不代表實際執行順序**。要判斷時序請用 Python 端的 print。

**改完一定要 `recalc()`**，否則 `mainOutput` 還是舊的。改寶石還要先
`build.skillsTab:ProcessSocketGroup(sg)`。

**`mainOutput` 在 build 載入前是 `nil`**，`load_build*()` 已經內建 recalc，
但 `newBuild()` 之後要自己叫一次。

**Lua 端沒有 `Inflate()` / `Deflate()`。** 壓縮原本由 `SimpleGraphic.dll` 提供，
headless 丟掉那顆 DLL 就一起沒了；而且**無法用 ctypes 回呼補上**——LuaJIT 在
ctypes 回呼回傳值時必定存取違規（回傳 0 個值正常，回傳 ≥1 個就當掉）。
實務上不影響：`load_build_code()` / `export_code()` 都在 Python 端做編解碼，
失去的只有 PoB 自己的 UI 匯入路徑（`ImportTab` / `CompareTab` / `PartyTab`），headless 用不到。

**沒有官方 API 文件，`api.md` 也只收了實際用過的東西**——光 `mainOutput`
就有 740 個欄位，收錄的遠不到零頭。**這是預期狀態，不是缺陷**：需要沒記載的
功能時自己挖，挖到了寫回 `api.md`。

底氣來源：**使用者的安裝目錄就是完整的 Lua 原始碼**，而且執行中的物件都能即時列舉。

```bash
grep -rn "Manaforged" "$APPDATA/Path of Building Community/Modules/CalcTriggers.lua"
```

三種手法（runtime 列舉 / grep 原始碼 / 差分比對）與可直接套用的 recipe
→ [`references/exploring.md`](references/exploring.md)

**本機沒有 PoB 的原始碼 repo**（這個設計刻意不 clone）。`spec/` 那些官方 API
用例要上 GitHub 查；但 `Modules/`、`Classes/`、`Data/` 安裝目錄裡都有，
本機的更快也更準——版本一定對得上。

---

## 相關

- 首次安裝 → [`references/install.md`](references/install.md)
- API 速查 → [`references/api.md`](references/api.md)
- **自己挖沒記載的用法** → [`references/exploring.md`](references/exploring.md)
- 星團珠寶（天賦排位機制、程式化建立與配點） → [`references/cluster-jewels.md`](references/cluster-jewels.md)
- **把遊戲內的角色同步進 PoB**（登入匯入優先、公開角色匯入當退路） → [`references/character-sync.md`](references/character-sync.md)
- 抓 poe.ninja 角色的 import code → `poe-ninja-builds` skill（角色頁上有個
  `<input>`，值以 `eN` 開頭就是），配 `playwright-cli` 取值
