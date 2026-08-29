> ⛔ **POE1 ONLY** ｜最後驗證：**2026-08-30**（Allflame 3.29）

# 操作坑

## 1. `goto` 之後畫面會先是 `Loading...`，立刻 snapshot 會拿到空殼

帶參數換頁時整個結果區重建，這段期間 snapshot 只有 header ＋ `Loading...` ＋ footer
（實測 69 行，完全看不出是失敗）。**永遠等表格出現再讀**：

```js
await page.waitForFunction(() => /Found [\d,]+ characters/.test(document.body.innerText), null, {timeout: 60000});
```

CLI 這邊沒有 waitFor 的話，就用 `playwright-cli eval` 輪詢那段文字，別靠 sleep 猜。

## 2. 每次重繪 ref 全部失效，而且**點擊會安靜失敗**

點完一個篩選、頁面重繪之後，上一份 snapshot 的所有 `eXXX` ref 就作廢了。
拿舊 ref 去 `playwright-cli click` **不會報錯、URL 也不變**，看起來就像那一格沒反應——
實測連續踩了三次（第二個技能格、Time machine 下拉、heatmap 按鈕）。

兩個對策，優先用前者：

- **改組 URL 直接 `goto`。** 篩選狀態全在 query string，不必點。順帶少發請求。
- 真的要點，每一步之間重抓 snapshot 拿新 ref。

## 3. React 不吃 DOM `.click()`

`page.evaluate(() => el.click())` 會回傳成功、元素文字也讀得到，但 handler 沒觸發、
URL 不變。要用 Playwright 的真實滑鼠：`elementHandle.click()`（必要時先 `scrollIntoViewIfNeeded()`）。
第一次探參數就是在這裡拿到 16 個空 URL 的。

## 4. 多值語意不一致：`class` 是 OR，其他全是 AND

| 查詢 | 結果 | 語意 |
|---|--:|---|
| `?skills=Winter+Orb` | 10,624 | |
| `?skills=Righteous+Fire` | 6,329 | |
| `?skills=Winter+Orb,Righteous+Fire` | **5** | AND |
| `?keypassives=Chaos+Inoculation,Blood+Magic` | 198（27,763 ∩ 23,114） | AND |
| `?items=Mageblood,Watcher's+Eye` | 24,151（41,796 ∩ 59,858） | AND |
| `?class=Elementalist,Occultist` | **33,966**（20,548 ＋ 13,418，精確吻合） | **OR** |

一個角色只有一個職業，`class` 走 AND 會恆為 0，所以站方特例成聯集。
**把「同類多選」當成「而且」來寫**，只有職業那格是「或」。
想在其他類別做「或」的分析，只能分次查再自己併——注意併集會重複計算兩者皆有的人。

## 5. 排除是 `!` 前綴，全類別通用

`?skills=!Winter+Orb` → 113,869，恰好等於 124,493 − 10,624。
UI 上的入口是格子選取後浮出的 `Exclude` 小按鈕（另一顆是 `Clear filter`）。

## 6. 有兩個東西不寫進 URL

- **Items 類別的 `Only show items of type` 下拉**（All／Amulet／…／Weapon）：
  只縮左側清單方便你找，不是查詢條件，`Found N` 不會變。
- 其餘視圖狀態都在 URL 裡，包括 `columns=`（有序清單）與 `heatmap=true`，
  兩者都可深連結、reload 後保留。

## 7. `timemachine` 與 `type` 會換掉整份快照

`type=exp` 與 `type=depthsolo` 各有自己的 snapshot id（實測 `1453-20260829-10410`
vs `1457-20260829-44826`）。`timemachine` 空字串＝最新，不是「全部時間」。

## 8. 聯盟用 slug，不是顯示名

`allflame`／`allflamehc`／`allflamessf`／`allflamehcssf`／`allflamer`／`allflamehcr`／
`allflamessfr`／`allflamehcssfr`／`standard`／`streamers`。
**寫錯 slug 不會報錯**，會落到 404 殼頁或別的聯盟；換聯盟後先確認 `Found N` 合理。

## 9. `playwright-cli run-code` 的 sandbox 沒有 `URL` / `document` 全域

解析 query string 用正則（`/[?&]columns=([^&]*)/`），碰 DOM 一律進 `page.evaluate`。
把 `document` 寫在 evaluate 外面會拿到 `ReferenceError`。

---

## 附：16 組篩選參數全數複驗

2026-08-30，每個參數各下一條單值查詢，全部回合理結果集（非 0、非全量）：

| 參數 | 樣本查詢 | `Found` |
|---|---|--:|
| （無） | baseline | 124,493 |
| `class` | `Occultist` | 13,418 |
| `items` | `Mageblood` | 41,796 |
| `skills` | `Winter Orb` | 10,624 |
| `skillmodes` | `Totem` | 6,302 |
| `vestigialmods` | `#% increased Rarity of Items found` | 1,088 |
| `secondascendancy` | `Farrul Bloodline` | 7,249 |
| `keypassives` | `Chaos Inoculation` | 27,763 |
| `anointed` | `Charisma` | 6,053 |
| `atlasskills` | `Mounting Modifiers` | 79,281 |
| `bandit` | `Eramir` | 103,589 |
| `pantheon` | `The Brine King` | 50,098 |
| `masteries` | `12% increased Mana Reservation Efficiency of Skills` | 55,235 |
| `runegrafts` | `Runegraft of Treachery` | 25,138 |
| `tattoos` | `Tattoo of the Ngamahu Firewalker` | 25,446 |
| `guardianitems` | `Leer Cast` | 25,844 |
| `allgems` | `Faster Attacks Support` | 62,113 |
| `weaponmode` | `Bow / Quiver` | 5,627 |

數字本身是 Allflame 當期快照，換聯盟即失效；這張表的用途是**證明參數名可用**。
