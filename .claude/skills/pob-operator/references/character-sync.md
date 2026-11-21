> POE1 only（PoB Community）｜最後實測：**2026-11-22**，3.30 Covens 聯盟

# 把遊戲內的角色同步進 PoB

無頭模式沒有 PoB 自己的下載函式（那是圖形介面那一層提供的），所以「抓資料」要在 Python 端做，
抓到的 JSON 再交給 PoB 匯入分頁的兩個函式。解析物品、對寶石插槽、配天賦都還是 PoB 原本的邏輯，
跟使用者在匯入分頁按按鈕走的是同一段程式。

> **這份文件記的是 2026-11-22 當時的取法，PoB 或官方更新後都可能過時。** 端點、標頭、欄位名稱對不上時，
> 以使用者安裝目錄裡的 `Classes/PoEAPI.lua`（請求怎麼發）和 `Classes/ImportTab.lua`（回傳怎麼用）為準，
> 核對後回來更新這裡。

資料來源有兩種，對應 PoB 匯入分頁上的兩種做法：

| | 登入匯入 | 公開角色匯入 |
|---|---|---|
| 需要知道 | 角色名稱 | 帳號（含 `#` 數字尾碼）＋角色名稱 |
| 前提 | 使用者在 PoB 裡登入過，憑證還沒過期 | 角色頁設成公開 |
| 資料完整度 | **完整**，含聯盟限定的裝備部位 | 缺聯盟限定部位 |
| 用到的憑證 | PoB 存在本機的存取權杖 | 無 |

**規則：憑證有效就用登入匯入；憑證不存在或已過期才退回公開角色匯入。**

兩者差在哪：3.30 的 Wickerman 部位（頭、軀幹、手、腳四格）只有登入匯入拿得到。實際踩過——
用公開匯入同步後結合秒傷少了 13%、生命少了 165，一度誤判成是使用者換的寶石和天賦造成的。
以後每個聯盟的新部位大概都會是同樣情況。

---

## 判斷流程

```
讀 Settings.xml 的 <Accounts> 標籤
├─ 有 lastToken，且 tokenExpiry 距現在超過 120 秒 → 登入匯入
│     └─ 請求回 401／403 → 當成憑證無效，退回公開角色匯入
└─ 沒有 lastToken，或已過期 → 公開角色匯入
      └─ 沒有帳號名稱 → 問使用者（或請他在 PoB 按一次匯入來續期，再走登入匯入）
```

退回公開匯入時**一定要告訴使用者**：這次同步不含聯盟限定部位，數字會偏低。

---

## 憑證在哪、怎麼碰

PoB 用 OAuth 登入後，把三樣東西寫在 `%USERPROFILE%\Documents\Path of Building\Settings.xml`
的 `<Accounts>` 標籤屬性裡：

| 屬性 | 內容 |
|---|---|
| `lastToken` | 存取權杖（請求時放在 `Authorization: Bearer …`） |
| `lastRefreshToken` | 續期用的權杖 |
| `tokenExpiry` | 存取權杖的到期時間，Unix 秒 |

三條規矩：

1. **權杖的值不能進對話、不能印出來、不能寫進任何檔案。** 檢查時只印「有沒有」和「還剩幾秒」。
2. **不要自己續期。** 續期（`grant_type=refresh_token`）會換發一組新的權杖，舊的立刻失效；
   PoB 的 `Settings.xml` 裡還是舊的那組，使用者下次開 PoB 就等於被登出。
   過期時的正確做法是請使用者在 PoB 的匯入分頁按一次匯入——PoB 會自己續期並存檔——然後重跑。
3. **只做唯讀請求。** 權杖的權限範圍包含 `account:trade`，不要拿去做角色資料以外的事。

存取權杖的有效期以小時計（實測時看到還剩 7 小時多；完整效期沒量過），所以每次都要現讀 `tokenExpiry`，不要假設。

```python
import os, re, time
settings = open(os.path.join(os.path.expanduser("~"), "Documents", "Path of Building", "Settings.xml"), encoding="utf-8").read()
tag = re.search(r"<Accounts[^>]*>", settings)
tok = tag and re.search(r'lastToken="([^"]*)"', tag.group(0))
exp = tag and re.search(r'tokenExpiry="([^"]*)"', tag.group(0))
left = int(float(exp.group(1))) - int(time.time()) if exp else -1
use_login = bool(tok and tok.group(1)) and left >= 120
print("stored login:", bool(tok and tok.group(1)), "| seconds left:", left)   # 只印這兩樣
```

---

## 方法一：登入匯入

一次請求拿到整隻角色：

```
GET https://api.pathofexile.com/character/<角色名稱>
Authorization: Bearer <lastToken>
User-Agent: Path of Building/<launch.versionNumber>
```

- User-Agent 照 PoB 自己的寫法（`Launch.lua` 裡是 `Path of Building/` 加版本號），
  版本號用 `p.eval("return tostring(launch.versionNumber)")` 取。這支 API 跟交易站不同，
  **不要**套用 `.poe_cookies.json` 的瀏覽器 User-Agent。
- 主機版在路徑插入平台：`/character/xbox/<名稱>`、`/character/sony/<名稱>`。
- 列出帳號下所有角色：`GET /character`。

回傳的 `character` 物件已經是匯入函式要的形狀，不必重組：

| 欄位 | 內容 |
|---|---|
| `equipment` | 身上的裝備（含藥劑、寶石） |
| `jewels` | 天賦樹上的珠寶 |
| `passives` | 天賦、專精、昇華 |
| `wickerman` | 3.30 聯盟部位，`inventoryId` 是 `VisceraHead`／`VisceraBody`／`VisceraArm`／`VisceraLeg` |
| `inventory` | 背包（匯入時用不到） |

```lua
local dkjson = require "dkjson"
local f = assert(io.open(JSON_PATH, "rb")); local s = f:read("*a"); f:close()
local c = dkjson.decode(s).character
local tab = build.importTab
c.passives = c.passives or {}
c.passives.bandit_choice  = c.passives.bandit_choice  or build.configTab.input.bandit or "None"
c.passives.pantheon_major = c.passives.pantheon_major or build.configTab.input.pantheonMajorGod
c.passives.pantheon_minor = c.passives.pantheon_minor or build.configTab.input.pantheonMinorGod
tab:ImportPassiveTreeAndJewels(c, true)          -- true：先清掉樹上原有的珠寶
tab:ImportItemsAndSkills(c, true, true, true)    -- 清裝備、清技能、忽略武器切換欄
```

聯盟部位是 `ImportItemsAndSkills` 自己處理的（它會跑一圈 `charData.wickerman`），不用另外呼叫。

---

## 方法二：公開角色匯入

三個端點，都在 `https://www.pathofexile.com/character-window/` 底下：

| 端點 | 參數 |
|---|---|
| `get-characters` | `accountName`（含 `#` 數字尾碼）、`realm=pc` |
| `get-passive-skills` | 另加 `character` |
| `get-items` | 另加 `character` |

- 角色公開時不需要 cookie，也不要帶 POESESSID。
- User-Agent 照專案規矩從 `.poe_cookies.json` 讀，不要寫死；請求之間留 1.5 秒。
- 沒給角色名稱時，從 `get-characters` 挑 `lastActive` 的那隻。

三份資料要自己拼成匯入函式要的形狀：

```lua
local tab = build.importTab
pas.bandit_choice = pas.bandit_choice or build.configTab.input.bandit or "None"
local cd = copyTable(char); cd.passives = pas; cd.jewels = pas.items
tab:ImportPassiveTreeAndJewels(cd, true)
local cd2 = copyTable(char); cd2.equipment = itm.items; cd2.guardian = itm.guardian
tab:ImportItemsAndSkills(cd2, true, true, true)
```

`get-items` 的回傳只有 `items` 和 `character` 兩個鍵，沒有聯盟部位——這不是漏傳參數，是這個端點就不給。

---

## 兩種方法共通的事

### 匯入進既有的檔，不要匯入進空白檔

先 `p.load_build(現有的檔)` 再匯入。匯入只會換掉天賦、珠寶、裝備、技能，**設定頁的東西會留著**：
頭目類型、盛怒層數、「偷取中」之類的條件、感電效果、自訂詞綴區塊。
從空白檔匯入的話這些全部要重填，而且使用者通常不記得自己調過哪些。

盜賊選擇和萬神殿官網不回傳，上面的程式碼會沿用既有檔的值。第一次匯入沒有既有檔時要問使用者，
預設值不能當真（踩過：假設幫 Alira，使用者其實是全殺）。

### 匯入之後一定要補的三步

1. **把主技能指回去。** 匯入會重建技能群組，主技能可能跑到別的群組，多段技能的「計算哪一段」也會重設。
   用寶石名稱找群組，設 `build.mainSocketGroup`、`sg.mainActiveSkill`、`srcInstance.skillPart`。
2. **重算手填的數值。** 感電效果那格是手填的，換過裝備就要重新求自洽值（見 `api.md` 的感電一節）。
3. **`recalc()` 之後存檔，再重新載入讀一次數字。** 存檔用 `build:SaveDB("code")` 取回 XML 字串自己寫檔。

### 交付時要講的

- 用了哪一種方法；退回公開匯入的話，明講缺了什麼。
- 同步前後的秒傷、生命。**差很多時先查是不是少了部位或設定，不要直接歸因給使用者的改動。**
- 使用者的 PoB 視窗如果正開著同一份檔，請他重新載入，否則他那邊一存檔就會把舊內容蓋回來。
- 存檔前先備份原檔。檔名通常帶等級和日期，等級變了就換檔名並移除舊檔。

### 匯入會把什麼弄掉

- 裝備列表裡**沒裝在身上的物品**不一定留得住（以別人的 PoB 為底時留下的範本物品尤其如此）。
  使用者有刻意留著備用的東西時，先記下來。
- 使用者在 PoB 裡手動加、但遊戲內沒有的東西（例如先放進去試算的珠寶）會被遊戲內的實際狀態取代。
  這是同步本來的意思，但要先確認使用者知道。

---

## 錯誤對照

實際跑過的只有「憑證有效、請求成功」這一條路。下表的 HTTP 狀態碼是照 PoB 原始碼（`Classes/PoEAPI.lua`）
和一般慣例整理的，**還沒有實際撞到過**；第一次撞到時回來核對並更新。

| 狀況 | 意思 | 做法 |
|---|---|---|
| `Settings.xml` 沒有 `lastToken` | 使用者沒在 PoB 登入過 | 公開匯入；想要完整資料就請他在 PoB 登入 |
| `tokenExpiry` 已過 | 存取權杖過期 | 請使用者在 PoB 按一次匯入來續期；或直接公開匯入 |
| 登入匯入回 401／403 | 權杖被撤銷或權限不符 | 同上，**不要重試、不要續期** |
| 登入匯入回 404 | 角色名稱打錯，或不在這個帳號下 | 用 `GET /character` 列出角色核對 |
| 登入匯入回 429 | 請求太頻繁 | 照回應標頭的等待秒數停，不要連打 |
| 公開匯入回 403 或空資料 | 角色頁設成私人 | 請使用者改公開，或改用登入匯入 |

---

## 現成的腳本

`pob-headless\output\` 裡有實際跑過的兩支（不在這個 repo 的版控裡）：

| 檔案 | 用法 |
|---|---|
| `import_my_character_oauth.py` | `<角色名稱> <要匯入進去的 build xml>`，原地存檔；憑證過期會直接停下 |
| `import_my_character.py` | `<帳號#1234> [角色名稱] [Builds 底下的子資料夾] [既有的 build xml]`，另存成 `my - <角色> Lv<等級> <日期>.xml` |

匯入後補主技能和感電的是 `fix_main_skill_and_report.py <build xml>`，裡面寫死了特定流派的技能名稱，
換流派要改。
