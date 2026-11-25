# 首次安裝 pob-headless

> 只有第一次需要。裝好之後每個 session 只要找得到入口資料夾就能直接用。

目標：在使用者本機建立一個 `pob-headless/` 入口資料夾，**依賴他已安裝的 PoB GUI**，
不複製第二份 PoB。

---

## Step 1：確認 PoB GUI 已安裝

預設路徑：

```bash
ls "$APPDATA/Path of Building Community/Launch.lua"
```

找不到就從登錄檔找：

```powershell
Get-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
                 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
  Where-Object DisplayName -like '*Path of Building*' | Select-Object DisplayName, InstallLocation
```

**都找不到 → 停下來請使用者先安裝 PoB Community**（<https://pathofbuilding.community/>），
不要嘗試自己下載安裝。

注意有兩個版本：`Path of Building Community`（POE1）與
`Path of Building Community (PoE2)`。**這個 skill 只驗證過 POE1。**

### 確認位元數相符

`pob.py` 用 ctypes 掛載 PoB 的 `lua51.dll`，**Python 與該 DLL 必須同為 64 位元**：

```bash
python -c "import struct; print('python bits:', struct.calcsize('P')*8)"
python - <<'PY'
import struct, os
p = os.path.join(os.environ['APPDATA'], 'Path of Building Community', 'lua51.dll')
d = open(p,'rb').read(0x400)
off = struct.unpack_from('<I', d, 0x3c)[0]
print('dll:', {0x14c:'x86 (32-bit)', 0x8664:'x64 (64-bit)'}.get(struct.unpack_from('<H', d, off+4)[0]))
PY
```

不相符就換一個相符的 Python（通常是裝 64 位元版）。

---

## Step 2：問使用者要裝在哪

用 AskUserQuestion，給三個選項：

| 選項 | 說明 |
|---|---|
| **跟當前工作專案並列在同一層（推薦）** | 例如專案在 `D:\work\myproj`，就建 `D:\work\pob-headless`。跟專案分離，但好找 |
| 和 PoB 應用程式資料夾同一層 | 例如 `%APPDATA%\pob-headless`。靠近它依賴的東西 |
| 其他位置 | 由使用者指定 |

建議理由（推薦第一個）：不會混進版控、不會被 PoB 的更新器掃到、而且下次
session 從專案往上一層就找得到。

---

## Step 3：建立入口

把這個 skill 的 `template/` 複製過去（**不要手打重抄**）：

```bash
D="<選定路徑>/pob-headless"
mkdir -p "$D/output"
cp "<skill 目錄>/template/pob.py"        "$D/"
cp "<skill 目錄>/template/slot.py"       "$D/"
cp "<skill 目錄>/template/make_boot.py"  "$D/"
cp "<skill 目錄>/template/README.md"     "$D/"
cp "<skill 目錄>/template/output_README.md" "$D/output/README.md"
```

`README.md` 是給**人**看的——使用者之後打開這個資料夾，要知道它是什麼、
會不會動到 PoB、能不能刪。`output/` 則是產出的落腳處，見 Step 3 之後的說明。

`pob.py` 會自己找 PoB 安裝位置，依序是：`POB_INSTALL` 環境變數 →
預設的 `%APPDATA%\Path of Building Community` → 解除安裝登錄檔
（會跳過同時裝在旁邊的 PoE2 版）。**不需要手改路徑。**

如果使用者的安裝在很特別的地方而三種都找不到，讓他設環境變數：

```bash
setx POB_INSTALL "D:\wherever\Path of Building Community"
```

---

## Step 4：產生開機入口

```bash
cd "<選定路徑>/pob-headless" && python make_boot.py
```

它會：讀安裝目錄 `manifest.xml` 拿版本號 → 從 GitHub 抓對應 tag 的官方
`HeadlessWrapper.lua`（快取到 `cache/`）→ 套上兩處修補 → 產生 `headless_boot.lua`。

預期輸出：

```
installed PoB version: 2.67.2
fetching https://raw.githubusercontent.com/.../v2.67.2/src/HeadlessWrapper.lua
wrote .../headless_boot.lua (262 lines)
```

**抓不到檔案時**（沒網路、或該版本沒有對應 tag）：請使用者從
<https://github.com/PathOfBuildingCommunity/PathOfBuilding> 下載
`src/HeadlessWrapper.lua`，然後 `python make_boot.py 路徑/HeadlessWrapper.lua`。

---

## Step 5：驗證

```bash
cd "<選定路徑>/pob-headless" && python pob.py
```

預期看到：

```
PoB installation : C:\Users\...\AppData\Roaming\Path of Building Community
version          : 2.67.2
lua              : Lua 5.1 / LuaJIT 2.1.xxxxxxxxxx
```

第一次跑會順便建立永恆珠寶快取（`built jewel cache: ...`），只會發生一次。

有 build 檔的話再測一次完整計算：

```bash
python pob.py "$USERPROFILE/Documents/Path of Building/Builds/<某個>.xml"
```

應該印出 `RESULT skill=... TotalDPS=... Life=... EHP=...`。
**請使用者用 GUI 開同一份 build 對一下數字**——對得上才算裝好。

### 確認沒有破壞使用者的安裝

```bash
python - <<'PY'
import hashlib, os, re
P = os.path.join(os.environ['APPDATA'], 'Path of Building Community')
man = open(os.path.join(P, 'manifest.xml'), encoding='utf-8').read()
bad = miss = n = 0
for m in re.finditer(r'<File name="([^"]+)"[^>]*sha1="([^"]+)"[^>]*/>', man):
    name, sha = m.group(1).replace('{space}', ' '), m.group(2); n += 1
    fp = os.path.join(P, name.replace('/', os.sep))
    if not os.path.exists(fp): miss += 1; continue
    d = open(fp, 'rb').read()
    if hashlib.sha1(d).hexdigest() != sha and hashlib.sha1(d.replace(b'\n', b'\r\n')).hexdigest() != sha:
        bad += 1
print('PoB 擁有的檔案 %d 個 | 被改過 %d | 遺失 %d' % (n, bad, miss))
PY
```

**被改過與遺失都應該是 0。** 不是 0 就要停下來查原因，不要繼續。

---

## Step 6：問使用者要不要記住路徑

裝好之後問一句（不強求）：

> 要不要我記住這個位置？這樣之後新的對話就不用重新找入口資料夾。

答應的話寫一條 `reference` 型 memory：

```markdown
---
name: pob-headless-entry
description: pob-headless 入口資料夾的位置（headless 驅動本機 PoB GUI）
metadata:
  type: reference
---

pob-headless 入口在 `<實際路徑>`。用 `pob-operator` skill 時直接從這裡起手，
不用再掃檔案系統。它驅動的是 `%APPDATA%\Path of Building Community` 的 PoB GUI 安裝。
```

別忘了在 `MEMORY.md` 加一行指標。

---

## 之後的維護

**PoB 自己跳更新就好，headless 不用動。**

唯一例外：PoB 改了 `HeadlessWrapper.lua` 本身（很少見，通常表現為開機時
`attempt to call a nil value` 或找不到某個 host function）——重跑
`python make_boot.py` 即可。PoB 大版本更新後順手重跑一次也不吃虧。
