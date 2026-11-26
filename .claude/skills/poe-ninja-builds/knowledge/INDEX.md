> ⛔ **POE1 ONLY**（`/poe1/builds`）｜聯盟基準：**Allflame**（3.29）｜最後整理：**2026-08-30**
> POE2 在 `/poe2/builds`，尚未實測；本目錄的事實不得直接套過去。

# poe.ninja builds 知識庫索引

目前有兩份：**怎麼用條件百分比做取向分析**，以及**瀏覽器操作的坑**。
站點的參數對照表不在這裡，在 [`../references/`](../references/)。

新增一條事實時：附到對應的檔案（或建 `<category>.md`），檔頭掛 POE1 橫幅與驗證日期，
然後在下面加一行 `- [檔名](檔名) — 中英雙語關鍵字`。
**量到的數字一律標日期與聯盟**——流派分佈每個聯盟從零開始。

- [analysis.md](analysis.md) — 取向分析 archetype meta analysis 條件機率 conditional percentage 樞紐 pivot 分母 denominator Found N characters 樣本數 sample size 前12名 top 12 尾巴看不到 Search filters 搜尋框 ｜ 標準流程 鎖群體 lock the cohort 對照組 contrast 沒有訊號也是訊號 no signal is signal 97% 定義性選擇 defining choice ｜ 問句對應 class 職業在玩什麼 skills 技能怎麼配 items 裝備值不值得 timemachine 漂移 drift day-1 week-5 硬派 hardcore ssf depthsolo 深度榜 口徑不同 different cohort 不可並排比較 ｜ 頂端 vs 中段 min-dps min-ehp 切層 ｜ 角色頁 character page Path of Building 匯入 import code PoB Search on Trade 不要批次抓 don't batch fetch ｜ 榜單下界 level 80 隱含條件
- [gotchas.md](gotchas.md) — 操作坑 pitfalls ｜ Loading 空白快照 empty snapshot 69 行 waitForFunction 別 sleep ｜ **ref 失效點擊安靜失敗** stale ref silent failure 不報錯 URL 不變 改組 URL goto ｜ React 不吃 DOM click evaluate el.click 無效 elementHandle.click 真實滑鼠 real mouse ｜ **多值語意 class 是 OR 其他 AND** multi-value semantics 交集 intersection 聯集 union 5 人 198 24151 33966 ｜ 排除 `!` 前綴 exclude Exclude Clear filter 三態 tri-state ｜ 不寫進 URL：Only show items of type 下拉 ｜ columns heatmap 可深連結 deep link reload 保留 ｜ timemachine type 換快照 snapshot id 1453 1457 空字串等於最新 ｜ 聯盟 slug 寫錯不報錯 allflamehc allflamessf standard streamers ｜ run-code sandbox 沒有 URL document 全域 ReferenceError 正則解析 ｜ **Cloudflare 驗證擋無頭瀏覽器** headless blocked Performing security verification 請稍候 Just a moment 403 HeadlessChrome User-Agent 一律 --headed 用完 close 不繞過驗證
