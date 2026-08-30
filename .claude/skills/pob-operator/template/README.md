# pob-headless

以無介面方式驅動**本機已安裝的 Path of Building Community**（POE1），
用 Python 讀取它算出來的任何數值。

**不是第二份 PoB。** 它載入的就是桌面版自己在跑的那些檔案，所以 PoB 自動更新後
這裡立刻同步，不需要維護第二份 checkout。

由 `pob-operator` skill 建立與使用。

```
pob.py              Python host：掛載 PoB 的 LuaJIT，載入 build，讀數值
make_boot.py        產生 headless_boot.lua
headless_boot.lua   開機入口（產生物，不要手改）
cache/              下載的官方 HeadlessWrapper.lua，依版本存放
output/             分析產出的暫存區（可隨時清空）
```

## 用法

```bash
python pob.py "路徑\某個build.xml"      # 快速檢查一份 build
```

```python
from pob import PoB
p = PoB()
p.load_build(r"...\Builds\某個build.xml")
p.load_build_code(code)      # poe.ninja / pobb.in / 論壇的 import code
p.eval("return tostring(build.calcsTab.mainOutput.TotalDPS)")
p.recalc()                   # 改完任何東西都要重算
```

完整的 API 與坑：見 `pob-operator` skill 的 `references/api.md`。

## 它會不會動到我的 PoB？

**不會。** `headless_boot.lua` 住在這個資料夾，不放進安裝目錄；工作目錄才設在
安裝目錄，所以它的 `dofile("Launch.lua")` 抓到的是 PoB 自己的入口。

唯一的寫入是 `Data/TimelessJewelData/*.bin`（永恆珠寶快取），而那是 GUI 版自己
也會產生的檔案——只在缺少時用 `zlib` 補上，內容與 PoB 自己解出來的位元組完全相同。

要自己驗證，用 PoB 的 `manifest.xml`（內含每個檔案的 SHA-1）比對，
「被改過」與「遺失」都應該是 0。

## 更新

**PoB 自己跳更新就好，這裡不用動。**

唯一例外：PoB 改了 `HeadlessWrapper.lua` 本身（很少見，通常表現為開機時
`attempt to call a nil value`）——重跑 `python make_boot.py`。PoB 大版本更新後
順手重跑一次也不吃虧。

## 安裝路徑

`pob.py` 自己找 PoB，依序是 `POB_INSTALL` 環境變數 → 預設的
`%APPDATA%\Path of Building Community` → 解除安裝登錄檔（會跳過 PoE2 版）。

## 已知限制

Lua 端沒有 `Inflate()` / `Deflate()`——壓縮原本由 `SimpleGraphic.dll` 提供，
headless 丟掉那顆 DLL 就一起沒了，而且無法用 ctypes 回呼補上。
編解碼改在 Python 端做（`load_build_code()` / `export_code()`），
實際失去的只有 PoB 自己的 UI 匯入路徑，headless 用不到。

## 這個資料夾可以刪嗎

可以。刪掉不影響 PoB 本體，重裝只要再跑一次 `pob-operator` skill 的安裝流程。
唯一要留意的是 `output/` 裡如果有還想保留的分析結果。
