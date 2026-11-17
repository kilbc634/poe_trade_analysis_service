# poe-build-upgrade 知識庫索引

> **POE1 only**｜最後整理：**2026-11-17**

## 歸檔規則

先問：**這件事只用一個工具就會遇到嗎？**

| 答案 | 寫到哪裡 |
|---|---|
| 是，只跟 PoB 有關（API、欄位、計算細節） | `pob-operator/references/api.md` |
| 是，只跟交易站有關（查詢、工藝規則、行情形狀、求解器） | `poe-trade-query` 的 `poe1/knowledge/` 或 `common/` |
| 是，只跟遊戲機制有關 | 查得到就不用記；查不到的寫進最相關的那個 skill |
| **否，要兩個以上的工具一起用才會遇到** | **這裡** |

**不記的東西**：具體價格、在架數、某一次的採買清單。這些幾小時就過期，只記「形狀」和「當時量到的規模」。

用請求裡的關鍵字 grep，中英文都試。

- [fast-solve.md](fast-solve.md) — 快速解 啟發式 heuristic 逐部位輪流改善 coordinate descent 隨機起點 restarts 不求最佳解 good enough 開季 league start 幾分鐘 5-10 分鐘 550 件 2000 變體 PoB 逐件實測 measure in PoB 工藝變體 craft variants 加法近似 additive 門檻當硬條件 hard constraint 不要加權 權重是手設的 hand-set weights 排序權重 search ranking 只影響池子 備選 alternates 換一件仍達標 沒有備選代表卡得很緊 弱點 不保證最佳 只看得到抓回來的 何時改用精確求解器 exact solver
- [pitfalls.md](pitfalls.md) — 坑 教訓 lessons 範本的珠寶沒清掉 tree jewels spec.jewels 存檔後重載 reload check 星團珠寶 cluster 多算了別人的東西 ｜ 感電 shock 手填 不會自己算 自洽 fixed point 反覆代入 Overcharge 觸發的閃電箭矢 ｜ PoB 沒模擬 not supported 寶石品質 額外投射物 PoB 說沒差不等於沒差 掛單敘述 ｜ 一次只換一樣 寶鑽藥劑 diamond flask 連其他藥劑一起換 ｜ 使用者指定的配法也要驗算 胸甲無生命 15% 生命專精 no life modifiers body 少 157 生命 損益兩平 ｜ 屬性崩掉 智慧不夠 傳奇不給屬性 藍色輔助 20 級 111 ｜ 工藝取最高值不是中間值 ｜ 負面詞綴要問 ｜ TotalDPS CombinedDPS 幻影射手 Mirage Archer ｜ 頭目設定 Uber Pinnacle 差三倍 ｜ 同名腳本 誤跑舊腳本 output 資料夾
- [league-start-market.md](league-start-market.md) — 開季 league start 掛單壽命 40 分鐘 被買走 改價 降價 重查 不沿用舊價 交付前確認在架 live check 甜蜜點 sweet spot 每 1% 傷害幾 c 邊際成本 marginal cost 傳奇數值 roll 中段 不追頂 便宜貨 bargain 先買 互補部位一次買齊 無關部位逐件買 傳送 hideout_token 逐件採買 賣家同名多件 佔位裝備 placeholder 作者清單的搜尋條件過嚴
