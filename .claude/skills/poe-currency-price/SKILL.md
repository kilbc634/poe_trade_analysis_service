---
name: poe-currency-price
description: Look up the real market price of Path of Exile currency and other bulk stackable items (currency, fragments, divination cards, essences, omens, soul cores, uncut gems… anything sold on the in-game Currency Exchange) for POE1 and POE2, and the divine/chaos/exalted exchange rates. Use whenever a task needs "what is X worth", "how many chaos is a divine right now", a budget converted between currencies, a list of fragment/card prices, or the last hours of a rate. Reads GGG's official public Currency Exchange API (actual filled trades, hourly, no login) through one script that already maps internal ids to item names and computes prices — do NOT price bulk items from trade-site listings. NOT for gear (rares/uniques are priced per item with poe-trade-query) and NOT for anything that cannot be sold on the Currency Exchange.
allowed-tools: Bash(python:*) Bash(py:*) Read Grep
---

> **POE1 與 POE2 通用**｜最後實測：**2026-11-20**（POE1 3.30 Covens、POE2 Forbidden Rites）

# 通貨與大宗物品查價（官方 Currency Exchange API）

通貨、碎片、命運卡這類大宗可堆疊物品的行情，一律用這個 skill 查。它讀的是遊戲內通貨交易所（POE1 的 Faustus）**實際成交**的每小時彙總，由 GGG 官方公開提供。

這個 skill 只有一支腳本 `cx.py`（Python 3.8+，只用標準函式庫），不需要登入、不需要 POESESSID、不需要瀏覽器。

---

## 用法

腳本在這個 skill 的目錄裡：`.claude/skills/poe-currency-price/cx.py`。

```bash
python cx.py price "Divine Orb" "現實碎片" "Mirror of Kalandra"   # 指定物品的價格（英文或繁中名稱）
python cx.py list --match fragment                          # 名稱含 fragment 的全部物品
python cx.py list --class DivinationCard --sort volume      # 依物品類別列表
python cx.py pair "Divine Orb" "Chaos Orb" --hours 24       # 一個交易對的逐小時歷史
python cx.py leagues                                        # 最近一小時有哪些聯盟、各自的頭條匯率
```

共用參數（放在子指令**之後**）：

| 參數 | 說明 |
|---|---|
| `--realm` | `poe1`（預設，POE1 PC）、`poe2`、`xbox`、`sony`（後兩者是 POE1 主機版） |
| `--league` | 聯盟名稱，要完全相符（不分大小寫）。**不給就自動挑最近一小時交易對最多的聯盟**，輸出開頭會標 `[auto: busiest league]` |
| `--hours N` | 合併最近 N 個已結束的小時（1–168）。`price` 不給時會自動放寬，見下 |
| `--json` | 機器可讀輸出，給其他腳本接 |

使用者有指定聯盟（例如專家模式、標準）時一定要帶 `--league`；自動挑到的幾乎都是當季軟核，不會是別的。

### `price`：最常用

```
POE1 (poe1) | league: Covens [auto: busiest league, pass --league to change] | traded 2026-11-20 11:00 - 11-20 12:00 (UTC+08:00)
rates: 1 div = 225.4 c

Reality Fragment（現實碎片）
    170.7 c = 0.7573 div   | volume 5,995 over 1 traded hour(s) | low-high 112.7 - 225.4 c
      vs Divine Orb       1 = 0.7729 div  (= 174.2 c)  vol 3,193      low-high 112.7 - 225.4 c  stock(max, latest h) 1,412
      vs Chaos Orb        1 = 166.7 c    (= 166.7 c)  vol 2,802      low-high 165.0 - 170.0 c  stock(max, latest h) 497
```

- 第一行是**綜合價**：把這個物品對各個基準通貨的成交全部換算成同一種幣後，以成交量加權。
- 底下每一行是一個實際的市場（`vs Chaos Orb` = 用混沌石買賣它的那個市場），有各自的成交價、成交量、當小時最低／最高成交比率與庫存。
- `price` 沒給 `--hours` 時：最近一小時沒成交的物品會自動放寬到 6 小時、再到 24 小時，並在該物品標 `** widened to last 6h **`。放寬過的價格比較舊，回報時要講。
- 名稱可用英文或繁中（繁中只有 POE1 有）；打不完整時若只對到一個市場就直接用，對到多個會列出候選。

### `list`：一整類

`--match` 是名稱子字串（英文或繁中），`a|b` 表示任一、重複給表示同時符合；`--class` 是物品類別。兩者可並用。`--classes` 會多印一行「這個聯盟有成交的類別與數量」，不知道類別名時先跑這個。

實測有成交的類別：POE1 是 `StackableCurrency`（約一半的物品都在這類）、`DivinationCard`、`MapFragment`、`DelveStackableSocketableCurrency`、`VaultKey`；POE2 另有 `SoulCore`、`Omen`、`Support Skill Gem`、`UncutSkillGemStackable`、`PinnacleKeyStackable` 等。`StackableCurrency` 太雜，要查其中一種請改用 `--match`（例如 `--match essence`）。

預設只列前 60 筆、依價格由高到低；`--limit 0` 列全部，`--sort volume` 依成交量。

### `pair`：匯率歷史

`pair A B` 印的是「1 個 A 值幾個 B」，預設 24 小時。要看行情有沒有在漂、或是要一個比綜合價更乾淨的匯率（見下面 POE2 那段）時用。

---

## 判讀：哪些數字可以信

**這是成交價，不是現在的掛單價。** 資料一小時一份，只有已經結束的小時；輸出開頭的 `traded … - …` 就是這份資料涵蓋的時段。所以它最多落後現況一小時，開季初期或行情劇烈變動時要把這段時差講出來，不要當成即時報價。

**成交量決定價格敢不敢用。** `volume` 是這個物品在該時段成交的個數。幾千以上的很穩；個位數到幾十的，一兩筆交易就能把價格拉歪，回報時要標明成交稀薄，必要時用 `--hours 6` 或 `24` 拉長時段再看。

**`low-high` 是該時段內最極端的成交比率，不是行情區間。** 有人掛錯價被吃掉就會出現離譜的數字（實測神聖石對混沌石的最低值出現過 1、30、150）。它的用途是看價差大不大、有沒有異常，不要拿最低值當「可以買到的價格」。另外，用神聖石交易的市場比率是整數比（例如 1 div 換 2 個），所以那一行的 low-high 會是 112.7、225.4 這種很粗的階梯。

**`!! markets disagree` 出現時，綜合價不可靠。** 這代表同一個物品在不同市場換算出來的價格差了 25% 以上。常見原因是其中一個市場成交很少，或是該市場只能用很粗的整數比成交。這時候**看使用者實際要用哪種幣付錢，就報那一行**，並說明綜合價不準。實測 POE1 Covens 一個小時內 715 個有成交的物品裡有 89 個會被標，大多是單價遠低於 1 div 卻有人用神聖石買的便宜東西。

**`[INDIRECT]` 表示這個物品沒有對任何基準通貨成交，** 是透過另一種物品再換算一次得到的價格，誤差更大，只能當參考。

**`stock` 是該市場最近一小時內掛單量的最高點，** 不是現在的庫存，只能看出市場深度的量級。

### 賽季末期（或任何沒人玩的聯盟）：價格會很怪，這是正常的

賽季快結束時玩家大量流失，市場不再流動，成交量掉到很低，同一個物品在不同市場的價格會對不起來、匯率逐小時亂跳。**這是市場本身的狀態，不是資料或腳本有問題**，回報時說明「賽季末期成交稀薄」即可，不要當成異常去追。

實例（2026-11-20，POE2 Forbidden Rites，使用者確認當時賽季將結束、基本上沒有玩家）：神聖石對崇高石一小時只成交 164 個神聖石，匯率在 418–522 ex 之間跳；Perfect Jeweller's Orb 在三個市場換算出來分別是 285、174、120 ex。

腳本對 POE2 一律換算成崇高石（ex）當基準，所以基準市場一薄，所有以 ex 表示的數字都會跟著不準。遇到這種情況：

- 輸出開頭的 `rates` 那行會另外印出參考通貨之間的直接市場，例如 `1 div = 11.71 c (direct market, vol 14,022 div)`。**神聖石與混沌石互換用這個直接市場的數字**，不要用兩個 ex 匯率相除。
- 物品價格優先看成交量最大的那一行市場的原始比率，綜合價只當概略值。
- 哪個市場還有量要當場看（`leagues`、`pair`），不要沿用上面這個實例的數字，也不要假設 POE2 平常就是這樣——這份觀察只來自賽季末期，賽季中的情況沒有實測過。

---

## 查不到的時候

| 腳本回報 | 意思 | 怎麼處理 |
|---|---|---|
| `NO MARKET in <league>` | 這個聯盟最近一小時連掛單都沒有 | 物品可能已從遊戲移除、不能在通貨交易所買賣，或真的沒人掛。先用 `poe-wiki` 的 `item` 指令確認這一季還拿不拿得到 |
| `NOT PRICED — N name(s) in the item table contain this, but NONE has a market` | 名稱表裡有，但市場上沒有 | 同上。**名稱表會保留已刪除的物品**，名稱查得到不代表東西存在 |
| `NO TRADES in the last 24 hour(s)` | 有掛單但 24 小時內沒有成交 | 沒有可用的成交價；可改用備援來源，或告知使用者沒有行情 |
| `several markets match` | 名稱太短，對到多個 | 用完整名稱再查一次 |
| `league … has no markets` | 聯盟名稱不對 | 錯誤訊息會列出目前有資料的聯盟 |
| 物品名稱前面有 `?`（例如 `?CurrencyStackedExalt`） | 名稱表還沒收錄這個 ID | 見下面「名稱對照」 |

**實例（2026-11-20）：** POE1 3.30 移除了所有聖甲蟲。名稱表裡仍有 195 個聖甲蟲名稱，但 Covens 與 Standard 都沒有任何聖甲蟲市場，查 `scarab` 會得到上表第二種回報。這是正確結果，不要改去別的來源硬找價格。

**不在通貨交易所賣的東西這裡一律查不到**，例如裝備與傳奇，那些走 `poe-trade-query`。

腳本本身失敗（HTTP 錯誤、連續四個小時都沒有資料）時，才退到備援來源 poe.ninja，端點寫在 `poe-trade-query/common/tricks.md` 的查價那一節；用了備援要在回覆裡講明。

---

## 資料來源與運作方式

- **價格**：`https://web.poecdn.com/api/currency-exchange[/<realm>]/<epoch>`。GGG 開發者文件把它列為 Public API，POE1 3.29.0（2026-07-21）起公開，不需要 OAuth。`epoch` 是整點的 Unix 時間戳，一小時一份，約 1.4 MB、1,600 多個交易對，涵蓋該 realm 的所有聯盟（含私人聯盟）。當前這個小時拿不到（回 404）。
- **每個交易對的原始欄位**：`volume_traded`、`lowest_stock`、`highest_stock`、`lowest_ratio`、`highest_ratio`，都是兩個物品各一個整數。沒有平均價、沒有買賣方向、沒有逐筆紀錄；有掛單但沒成交的交易對也會列出來（成交量為 0），腳本算價時已排除。
- **價格算法**：一個市場的成交價 = 對方成交量 ÷ 本方成交量。基準通貨以外的參考通貨（POE1 的神聖石；POE2 的神聖石與混沌石）先由它對基準通貨的市場定價，其他物品再把各市場的成交換算成基準通貨後加總相除。
- **名稱對照**：資料裡只有內部 ID（`Metadata/Items/Currency/CurrencyModValues` = 神聖石）。腳本從 RePoE（`repoe-fork.github.io`）下載對照表，快取一週。RePoE 在新賽季初期會缺新物品，POE1 會再到 poewiki 補查（3.30 的 Primordial Exalted Orb、Originator's Exalted Orb 就是這樣補到的）；POE2 沒有這個補查，缺的會顯示成 `?` 加 ID 尾段，可以直接拿那段尾巴當名稱查，例如 `price StackedExalt`。
- **快取**：放在系統暫存目錄的 `poe-currency-price/`（可用環境變數 `POE_CX_CACHE` 改位置）。已發布的小時不會再變，所以快照會保留 72 小時重複使用；第一次查 24 小時歷史要下載 24 份，約需半分鐘，之後就是即時的。
- **用量**：腳本每次網路請求間隔 1 秒。官方文件要求追到最新一份後等下一個整點再請求，腳本的快取已經做到這點，不要自己另外寫迴圈輪詢。
- 腳本對外只連 `web.poecdn.com`、`repoe-fork.github.io`、`www.poewiki.net` 三個主機，User-Agent 是固定的工具名稱，不帶任何使用者資訊。
- GGG 文件註明舊的歷史資料日後可能被移除；需要長期歷史要自己另存，這個 skill 不負責。
