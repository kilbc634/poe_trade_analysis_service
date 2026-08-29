> ⛔ **POE1 ONLY** — 這裡放 `/poe1/builds` 的 URL 參數對照。**不得放入 POE2 資料。**

# poe.ninja builds 參考表

**實測日期 2026-08-30，聯盟 Allflame（3.29），快照 `1453-20260829-10410`（`type=exp`）。**
表格內容是**參數名與語法**，不是行情數字，換聯盟不會失效；
但站方改版會改，對不上時照下面的方法重測。

| 檔名 | 欄位 | 筆數 |
|---|---|--:|
| `filters.tsv` | `category<TAB>param<TAB>multi_semantics<TAB>sample_value<TAB>notes` | 17（16 組面板 ＋ class） |
| `columns.tsv` | `group<TAB>label<TAB>slug<TAB>default` | 53（52 可切換 ＋ 固定的 Name） |

⚠ 一列一筆是硬性前提（逐行 grep 用）。`sample_value` 內的 `%` 已寫成 `%25`。

## 怎麼重測

參數名是「點一格、讀 URL 差異」測出來的。React 的 handler 不吃 DOM `.click()`，
**必須用真實滑鼠點擊**（Playwright 的 `elementHandle.click()`），否則 URL 不會變、
還會安靜地看起來像成功。

```js
// playwright-cli run-code --filename=probe.js
async page => {
  const BASE = 'https://poe.ninja/poe1/builds/allflame';
  const out = [];
  const cats = await page.evaluate(() =>
    [...document.querySelectorAll('h2')].map(h => h.textContent.trim())
      .filter(t => t !== 'Shrine Belt Buffs'));   // 這個是 Vestigial Modifiers 的外層標題，沒有自己的格子
  for (const cat of cats) {
    await page.goto(BASE);
    await page.waitForFunction(() => /Found [\d,]+ characters/.test(document.body.innerText), null, {timeout: 60000});
    const h = await page.evaluateHandle((cat) => {
      const x = [...document.querySelectorAll('h2')].find(e => e.textContent.trim() === cat);
      return x ? x.closest('section').querySelector('[role=checkbox]') : null;
    }, cat);
    const el = h.asElement();
    if (!el) continue;
    await el.scrollIntoViewIfNeeded();
    await el.click();                              // ← 真實點擊
    await page.waitForTimeout(1500);
    out.push({ cat, url: decodeURIComponent(page.url().replace(BASE, '')) });
  }
  return out;
}
```

欄位 slug 則是開 Columns 下拉、逐格點、diff `columns=` 參數測出來的。
下拉裡的格子**不是** `[role=checkbox]`（那 177 個全是篩選面板的），
要從 `Reset columns` 按鈕往上找面板容器、抓裡面的 `input[type=checkbox]`（52 個），
再點它的 `closest('div')`。

`run-code` 的 sandbox 沒有 `URL` 與 `document` 全域 —— 解析 query string 用正則，
碰 DOM 一律包在 `page.evaluate` 裡。
