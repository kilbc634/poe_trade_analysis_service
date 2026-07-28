# Query tricks & API gotchas — realm-agnostic (查詢技巧與陷阱，兩款遊戲共用)

Hard-won facts about how the trade **site** behaves, and about method that doesn't depend on which game you're pricing. Check before trusting a filter to do what its name suggests.

> **What belongs here:** transport (Cloudflare, auth, rate limits) and method skeletons. **What does NOT:** any stat id, filter field name, currency, item, mechanic, price, or mod-text format — those live in `<realm>/knowledge/`. See `../SKILL.md`.
>
> **⚠ 跨 realm 適用性：** most of what follows was measured against **POE2's** endpoints, because that's where the bulk work has been done. The *mechanisms* are site-level and hold on POE1; the *numbers* need per-realm confirmation. Status as of **2026-07-28**:
> - **Confirmed on POE1 too:** fetch batch cap = **10** hashes, search result window = **100** hashes (`poe1/QUERY.md`), and the rate-limit budget being **one shared pool across both games** (see below).
> - **Still POE2-only measurements:** the rate-limit tuples snapshot, the anonymous hidden-quota threshold (~30 fetches), and the safe inter-request floors. Don't quote those as POE1 fact until someone has measured them there — but do expect the same shapes.

## Cloudflare 403 on plain HTTP: it's the User-Agent (純 HTTP 被 CF 擋：UA 是關鍵)

Controlled test 2026-07 against the search POST: bare `User-Agent: Mozilla/5.0` → **403 blocked**; full realistic UA (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36`) → **200, even with no cookies at all**. So for anonymous price checks: send a full browser UA and skip the browser entirely.

**Escalation ladder if a plain-HTTP call still gets blocked (user-confirmed policy 2026-07):**
1. Full realistic UA (usually enough — Cloudflare scores a normal UA high).
2. Add cookies from `.poe_cookies.json` (project root, gitignored) — holds `POESESSID`, `cf_clearance`, and the UA they were captured under. `cf_clearance` is bound to **IP + UA**, so always send it with the stored `user_agent` (but it is only needed for the Cloudflare-gated `/data/*` endpoints, NOT search/fetch). Do NOT store POETOKEN (short-lived login-only OAuth JWT, not needed for trade APIs). **A logged-in POESESSID matters for far more than whisper/buy: it puts search/fetch on a SEPARATE, near-unlimited rate-limit pool** — see "The header counters are a DECOY" below. Prefer sourcing it from `setting.py` (env-backed) over the cookie cache for bulk jobs.
3. Still blocked → add full browser-parity headers (template from a real Chrome capture): `accept: */*`, `accept-language`, `origin: https://www.pathofexile.com`, `referer: <this realm's trade search page URL — see the realm's QUERY.md>`, `x-requested-with: XMLHttpRequest`, `sec-fetch-dest: empty`, `sec-fetch-mode: cors`, `sec-fetch-site: same-origin`, and the `sec-ch-ua*` client-hint family matching the UA (`sec-ch-ua: "Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"`, `sec-ch-ua-mobile: ?0`, `sec-ch-ua-platform: "Windows"`, …).
4. Last resort → open-poe-trade headed browser, let the challenge clear, then go back to plain HTTP.

**Refresh-on-trigger rule:** **any time a headed browser gets opened for POE at all** — step 4 clearing a challenge, *or* an expired POESESSID forcing the in-page-fetch fallback, *or* just `open-poe-trade` for a UI task — immediately re-export cookies + UA and overwrite `.poe_cookies.json` (playwright: `page.context().cookies('https://www.pathofexile.com')` filtered to POESESSID/cf_clearance, plus `navigator.userAgent`), so the cache always holds the latest known-good clearance. **`.poe_cookies.json` is a disposable cache** — it expires, and it may simply not exist; treat "the browser was open and logged in" as the one chance to refresh it and never assume the file is current (check `saved_at`).

> ⚠ **This step can be permission-blocked, and then it fails silently (2026-07-28).** Reading the cookie values out of the browser was **denied by the permission classifier** ("Blocked by classifier"), so that session's refresh never happened and the cache stayed 24 days stale while the task carried on via in-page fetch. Consequences to plan around:
> - **Never assume the refresh succeeded.** After attempting it, re-read `saved_at` to confirm it actually moved; if it didn't, say so instead of reporting the cache as refreshed.
> - The task itself does **not** need the cookie: in-page fetch already runs on the logged-in pool. The refresh only benefits *future* plain-HTTP runs — so a denial is not a reason to stop or to re-ask.
> - To make it work unattended, the user must allow that specific export command in settings (`permissions.allow`); otherwise the only path is the user refreshing `setting.py` / the cache by hand. Per [the POESESSID-expiry policy below](#poesessid-過期時的處置順序使用者指定-2026-07-28先問再-fallback), ask them once, don't loop on it.
>
> **Ready-made:** `.claude/skills/open-poe-trade/refresh_poe_cookies.py` does the export + write (with a downgrade guard, and it re-reads the file to report what actually landed). It is allowlisted in `.claude/settings.local.json`, so it runs unattended. Details in that skill's **Step 4**.

In-page `fetch` (browser already open) remains a valid alternative to 2–4. Rate-limit etiquette applies on every path: batch fetches at the endpoint's cap (**≤10 hashes — confirmed on both POE1 and POE2**), and hold the inter-request floors below (**search 2s / fetch 1.5s**, measured safe on the authed pool).

## Rate-limit headers: the actual rules (官方限流規則與 header 語義)

Official docs: <https://www.pathofexile.com/developer/docs/index#ratelimits>. Every trade API response carries:

- `X-Rate-Limit-Policy` — policy name (search: `trade-search-request-limit`, fetch: `trade-fetch-request-limit`; per-policy budgets, shared across endpoints with the same policy)
- `X-Rate-Limit-Rules` — active rule dimensions (`Ip`, sometimes `Account`, `Client`)
- `X-Rate-Limit-<Rule>` — comma-list of `max_hits:period_s:penalty_s` (ALL windows apply simultaneously)
- `X-Rate-Limit-<Rule>-State` — same shape: `current_hits:period_s:active_restriction_s` (3rd number >0 = currently locked out)
- On breach: 429 + `Retry-After` (seconds until the restriction expires)

Snapshot 2026-07-08, **POE2 endpoints** (dynamic — **reread at runtime, never hardcode**): **search** IP rule `8:10:60, 15:60:120, 60:300:1800`; **fetch** anon IP `12:4:10, 16:12:300`, but authed shows IP `12:4:60, 16:12:60` **plus** `Account 6:4:10`. These numbers drift between readings (search was `5:10:60,15:60:300,30:300:1800` on 07-05) — "limits can change at any time depending on our requirements", and observed `Retry-After` values (600/605s) match no published tuple. Parse the live headers.

**Counters are per-policy** (verified): a fetch hit does not touch the search policy's `-State` and vice versa; the two budgets run in parallel. Within one pool a fired penalty is enforced across ALL trade endpoints (a fetch during a search-triggered lockout still 429s; see the 429 section below).

**The budget IS shared across games — measured 2026-07-27.** Same POESESSID, searches interleaved POE1 → POE2 → POE1: all three returned `X-Rate-Limit-Policy: trade-search-request-limit`, and `X-Rate-Limit-Ip-State`'s long window counted straight through them — `11:10800` → `12:10800` → `13:10800`. The bucket is keyed on (IP × identity) and the policy is an endpoint-*family* name, not a per-game one. **So a bulk POE2 run eats POE1's budget and can lock you out of both.** Plan the two games as one pool.

### The header counters are a DECOY — the real limiter is hidden and login-gated (2026-07-08, the big one)

Measured directly with `ratelog.py` (2.5s spacing, per-request Ip-State logged). This overturns the old "just obey the headers" strategy:

- **Anonymous fetch has an UNDOCUMENTED hidden quota.** The visible `X-Rate-Limit-Ip-State` sat steady at `2:4:0, ~5:12:0` — nowhere near the `12`/`16` caps — for **32 straight 200s, then request #33 returned 429 `Retry-After: 600` with NO `X-Rate-Limit-*` headers at all**. So `_throttle_wait()` (reacts only to visible near-cap counters) is **structurally blind** to what actually penalizes you. This is why bulk anon runs hit ~600s walls "for no reason" every ~30 requests. It is count-based over a multi-minute rolling window, not rate-based — slower spacing (6s vs 2.5s) only delays the wall. Anon fetch throughput is hard-capped ≈30 fetches / ~10 min.
- **Authenticated (POESESSID) is a SEPARATE pool with no such wall.** Same endpoint/IP/instant: anon → 429 locked, authed → 200 clean. Authed adds an `Account` dimension (`Rules=Account,Ip`); crucially **even its `Ip` counter reads clean** while the anon `Ip` is locked — GGG keys the bucket on (IP × identity), so an anon IP penalty does NOT touch authed traffic. A 50-fetch back-to-back authed run hit **zero** penalties (anon died at 33). The hidden quota does not apply to logged-in traffic (or is far higher — untested past 50).
- **Practical rule: always send a logged-in POESESSID for bulk work.** both `gear_combo_optimizer_poe1.py` and `gear_combo_optimizer_poe2.py` read it from `setting.py` by default and refuses to run anonymously unless `--anon` is passed (tiny jobs only). The 32-hex `POESESSID` authenticates search/fetch; `cf_clearance` is NOT needed for these (only `/data/*` is Cloudflare-gated). Detect an expired POESESSID at runtime: a cookie'd request coming back with `Rules=Ip` (no `Account`) did not authenticate → refresh it.
- **Anti-rapid-click is yet another separate layer.** ~4 requests in ~2s returns 429 "wait 60s" while the visible state is only `4:10:0` (far below cap) — a burst guard the headers can't predict. Fixed inter-request floors are what prevent it, NOT the header logic.
- **Measured floor (authed pool, 2026-07-08, user-requested speed test) — this bullet is the authoritative pacing number, everything else in this file defers to it: search 2s + fetch 1.5s is SAFE** when combined with the header-adaptive `_throttle_wait()`. A full 33-search / ~190-fetch-batch authed run at that pace hit **zero 429s**. Mechanics: at 2s the search window nears cap every ~2 POSTs and the throttle inserts a 5s wait (so effective search pace self-caps ~3.5s — faster fixed pacing than 2s buys nothing); fetch at 1.5s ran clean throughout, so the old 2.5s fetch floor was conservative. The floors only guard bursts; the adaptive throttle does the real work. (Anon pool untested at this pace — its hidden quota walls you anyway.)

### Debunked: VPN IP switching does NOT help (2026-07-08)

Tempting idea (a former `--vpn-pause` mode, now removed): pause on a long wait, switch VPN exit, resume — betting the penalty is per-IP. **Measured false.** Across manual VPN switches the anon `Retry-After` kept counting *down* continuously (600→538→468→331→clear) instead of resetting — the "clean window" was just the penalty timer expiring, not the IP change. Commercial VPN datacenter exits are also often pre-poisoned by other users' anon traffic (a freshly-switched exit 429'd on its first request). And the hidden anon quota is enforced regardless of IP. Switching VPN is dead weight; **logging in is the actual fix.** Kept the lesson, deleted the mode.

## Rate-limit penalties are long and shared (429 懲罰期長且全 API 共用)

**This section describes ANONYMOUS behavior — logging in (above) sidesteps most of it.** If you're stuck anonymous:
- **The penalty blocks ALL trade API endpoints** (search *and* fetch) within the pool, not just the violated one. A fetch during the penalty just hangs on 429s — don't "use the other endpoint meanwhile".
- **Never retry during the penalty.** Each blocked request risks re-extending it. Sleep the full `Retry-After` + a few seconds, then resume.
- The fetch wall is the hidden ~30-request quota documented above (429 + ~600s, no headers), NOT the visible windows — it hits at ~14–33 batches regardless of 2.5s vs 6s spacing. For 60+ batch anon jobs, budget one ~600s penalty per ~25–30 batches, or front-load the must-have pools. The search POST budget is also small (~7–11 in a minute before a multi-minute 429).
- **Always cache every search + every fetched batch to disk** keyed by (search, range) so a killed/crashed run resumes free — this is what makes penalty-sleeping and login-refresh restarts cost nothing.
- Long waits → run the whole resume plan as one background script with 429-aware retry (read `Retry-After`, sleep, retry once), not foreground calls that time out mid-wait.

## Deep-fetch a search's price ladder without re-searching (免重搜抓高價端)

A search response stores a **result-hash window** of up to **100** (confirmed on both POE1 and POE2). Since results sort by price asc, the later hashes (`[40:100]`) are the *more expensive tranche* of the same query — fetch them directly with the same `query_id`, no new search POST needed. Ideal when the cheap end is exhausted and you want to see what more budget buys (the price/quality frontier) without spending search-rate budget.

## Probe the ceiling BEFORE building pools (先探頂再撈池, user-taught 2026-07)

Don't jump straight to the pooling script with guessed thresholds — cheap-end-sorted pools make every budget tier collapse to the same cheap answer (sampling bias), which under-serves a "best within budget X" request. First run a few **interactive probe searches** per slot to learn what the top end looks like:

1. Assume the extreme: one slot eating ~80% of the total budget. Add a price cap at ~80% of budget — use the **literal-currency mode** (`trade_filters.price` with an explicit `option` naming the realm's high-value trade currency), because the equivalent-mode internal rate is unreliable — and crank the stat mins up.
2. Read the `total` count from the search response (no fetch needed). **>200 results ⇒ conditions too conservative — raise the stat mins**; near-0 ⇒ back off. Iterate to find where the mod ceiling sits for that slot & budget.
3. Only then define the pool searches around those discovered ceilings (a high-end pool + a mid pool per slot), fetch, and optimize.

The 80% / 200-count numbers are heuristics, not rules — judge from actual counts. And when reporting: the user's "best in budget" means **max score while spending up to the budget**; the CP sweet spot is supplementary info, not the answer.

### ⚠ 先 fetch 十幾件真貨，再開始數量探頂（2026-07-28 教訓，代價 46 次搜尋）

數量探頂（只讀 `total`）的盲點是**它不告訴你物品實際數值**，所以起始門檻只能猜——猜低了就得一輪一輪往上加。
實測踩過：因為「30c 買 6 件 ⇒ 每件 5c ⇒ 只買得到破爛」這個直覺，門檻從 L60/R50 起跳，
前 3 輪（46 次搜尋）全打在天花板以下白費掉；直到隨手 fetch 10 件回來，
才看到 **1 chaos 就有 L143／三抗 73 的頭盔**，門檻要一次拉高 2 倍以上。

**正確順序：先挑一個寬鬆條件的 pool，price asc 撈 10–30 件回來看實際數值分佈，用真實數字定探頂格線。**
一次 fetch（1 search + 1 fetch batch）的資訊量遠勝幾十次計數探頂，而且更省限流配額。
價格帶越低這個偏差越大——低價帶不是「垃圾裝」，是**大宗商品**。

## Multi-slot gear combos: pool per slot, optimize locally (多部位配裝法)

> **Method skeleton only.** The scoring function, which stats you parse out, the currency, the mod-text format, and every measured number are **game-specific** — get them from `<realm>/knowledge/`.

For "buy N pieces within budget X satisfying joint constraints (some total across the whole set)": **don't try to encode the joint constraints into any single search** — the site can't express them. Instead:

1. **Per slot**, run 2–3 searches: a cheap broad pool + a mid pool + a high-spec pool at the probed ceiling (thresholds from the ceiling probes above, never guessed). Price asc.
2. **Fetch ~40 per search**, plus the deep-fetch tranche when you want the expensive end.
3. **Parse into normalized candidates** — price converted to one currency, plus whatever stats the build's scoring function needs. Mod-text parsing rules are realm-specific; see the realm's KB.
4. **Brute-force the slot cross-product locally.** Small cases (100³) are instant; more slots need the staged combine below.
5. **Report the best combo per budget tier.** The marginal-value curve is the real deliverable — it shows the user where spending stops paying.

**Bucket-cap accuracy: convergence-test it, don't trust one cap.** In the staged combine, bucket pruning (`prune_groups`) is the only lossy step versus full brute force (astronomically large at 6 slots — not an option). Practice: **default cap 50000; for a final deliverable rerun with the cap doubled — if the answers don't change, call it converged.** Kept-counts saturate once bucketing reaches its finest granularity, and caps beyond that point change nothing; that saturation point is case-specific, so measure it rather than assuming. Headline tiers (sweet spot / max budget) converge much earlier than mid tiers.

**Reusable implementations — one per realm, pick the matching one:**

| realm | script | 求解器 | 附帶 |
|---|---|---|---|
| **POE2** | [`../scripts/gear_combo_optimizer_poe2.py`](../scripts/gear_combo_optimizer_poe2.py) + [`verify_links_poe2.py`](../scripts/verify_links_poe2.py) | 分階組合 + 桶截斷（有損，要測收斂） | 驗證另開一支 |
| **POE1** | [`../scripts/gear_combo_optimizer_poe1.py`](../scripts/gear_combo_optimizer_poe1.py) | **截頂 + Pareto + 3-D 後綴最大值（精確）**，另有 `POE_FAST` 瘦身模式 | 探頂／撈池／求解／驗證／收斂／交付**全部內建**，子命令切換 |

兩支的端點、欄位名、stat id、幣別、詞綴正則**都是各自遊戲的 profile，不可互抄**（見各自檔頭）。
POE1 那支另有兩個實用件：**雙傳輸層**（POESESSID 死了自動改走已登入瀏覽器的 in-page fetch）與
**`selftest` 子命令**（拿小樣本跟六層 for 迴圈暴力解對拍，改動求解器後必跑）。 Don't rewrite from scratch — copy it to the scratchpad, refresh the currency rates from the realm's exchange-rate notes, edit CONFIG/SEARCHES/constraints for the task (pool thresholds from ceiling probes first!). Scaling warning baked into the script: windowed Pareto checks and unbounded combo accumulation OOM at 6 slots — keep `prune_groups()` and the heap join as-is.

**Default output rule (user-confirmed 2026-07):** for price checks, do NOT navigate the browser to the results page — just give the user the search-result URL(s) to copy (build them per the realm's QUERY.md). This holds even when a browser happens to be open. Only `goto` the results page when the user explicitly asks to see it.

## POESESSID 過期時的處置順序（使用者指定 2026-07-28，**先問再 fallback**）

發現 POESESSID 過期（回應 `Rules=Ip`、沒有 `Account`）時，**不要自己默默切備援**：

1. **先問使用者要不要手動更新**——他偏好自己去拿一把新的貼進 `setting.py` / 環境變數，
   因為那才是能讓後續純 HTTP 腳本、`scavenger.py` 都恢復正常的根治做法。
2. **等 60 秒。** 60 秒內沒回覆，就直接走下面的 in-page fetch 備援，不要卡住整個任務。
3. 之後若使用者補上了新的 POESESSID，優先切回純 HTTP（快得多，也不必開瀏覽器）。

**「先問」的理由**：in-page fetch 只是繞過去，`setting.py` 裡那把仍然是壞的；
下次任何不經瀏覽器的工具照樣會失敗。

## UA 紀律：**絕對不要寫死 UA**（使用者提醒 2026-07-28）

使用者的實測經驗：**UA 不合理很容易讓 POESESSID 被註銷、得重新拿。** 因此：

- **UA 的唯一來源是 `.poe_cookies.json` 的 `user_agent`**（那是 cookie 被擷取時的真實 UA）。
  程式裡只能放「檔案不存在時」的最後備援值，**不能當常態值用**。
  `cf_clearance` 綁 (IP × UA)，UA 一漂就等於拿錯鑰匙。
- **寫死版本號會隨時間爛掉**：本檔記的 `Chrome/149.0.0.0` 是 2026-07 驗證過的，
  但真實瀏覽器會自動更新；哪天實際是 Chrome 152，寫死的 149 就與瀏覽器 session 不一致了。
  refresh cookie 時**一定要連 `user_agent` 一起重新匯出**（見上面的 refresh-on-trigger 規則）。
- **能走 in-page fetch 就別自己組 UA**：頁內請求帶的是瀏覽器自己的真實 UA，
  與它自己的 session 天生一致，是最安全的組合。2026-07-28 那次六部位配裝，
  37 個池子與所有在架驗證都走頁內，只有探頂搜尋走純 HTTP。
- 診斷用：session 是**因為 UA 不一致**被砍，還是**單純過期**？看 cookie 檔的 `saved_at`。
  2026-07-28 那次兩把都是第一次請求就 `Rules=Ip`，而檔案是 07-04 存的（24 天前）——**那是自然過期，不是 UA 問題**。

## POESESSID 過期時的備援：用已登入的瀏覽器做 in-page fetch（2026-07-28 實測）

`setting.py` 與 `.poe_cookies.json` 兩把 POESESSID 都過期（回應只有 `Rules=Ip`、沒有 `Account`）時，
**不必向使用者要新 cookie，也不必去瀏覽器裡把 cookie 撈出來**（後者可能被權限層擋下，而且沒必要）：

1. `playwright-cli open --headed --persistent` 開站——persistent profile 通常還留著登入狀態，
   用 `playwright-cli --raw eval "(async()=>(await fetch('/api/profile')).status)()"` 驗，**200 = 已登入**。
2. 之後所有 search / fetch 都在頁內 `fetch` 打。實測 in-page 請求回 **`Rules=Account,Ip`**，
   也就是**走的就是已登入的那個池**——等於完全繞過匿名池的隱藏配額，不需要拿到 cookie 本身。

**踩過的兩個坑：**

- **JS 必須用檔案傳，不能塞進 argv。** `playwright-cli run-code --filename <file>`（`eval` 的
  `--filename` 是「把結果存檔」，語義不同，別搞混）。直接把 JS 當命令列參數傳，Windows 的
  `cmd.exe` 會吃掉字串裡的字面 `%`——抗性正則 `/\+(\d+)% to Fire Resistance/` 裡全是 `%`，
  結果是頁面回 `SyntaxError: Unexpected token ')'`，看起來像 JS 寫錯，其實是 shell 改了內容。
- **npm 的全域指令在 Windows 不是 PE 執行檔**：`subprocess.run(["playwright-cli", ...])` 會
  `FileNotFoundError: [WinError 2]`，要指到 `%APPDATA%\npm\playwright-cli.cmd`。

在頁內就把詞綴解析完、只回傳精簡欄位（每件 ~10 個數字），別把整包 listing JSON 送回來——
CLI 的 stdout 會直接進上下文。限流照樣要守：頁內同樣讀得到 `X-Rate-Limit-*`，把 header 節流搬進 JS。

## 多部位配裝的精確解法：抗性截頂 + 3-D 後綴最大值 join（2026-07-28）

> 📊 **兩套求解器的分層／失真點／耗時對照，以及「換一套新演算法時該量什麼」的樣板，
> 集中在 [`optimizer-algorithms.md`](optimizer-algorithms.md)。** 要比較世代差異先看那份，
> 本節只講這個精確解法本身。

`gear_combo_optimizer_poe2.py` 的 `prune_groups()` 桶截斷是**有損**的（要靠加倍測收斂）。
六部位、每部位 ~120 候選這種規模，其實有**不需要截斷**的精確做法：

1. **把每組的抗性總和截頂在需求值**（需要火 129，那 F=150 和 F=129 完全等價）。
   溢出的抗性一文不值，狀態空間立刻從無界縮成 `(129+1)×(62+1)×(91+1)` 的小格子。
2. **每個截頂後的 `(F,C,L)` 只留 price/life 的 Pareto 前緣**——查詢永遠是
   「抗性 ≥ X 時最便宜／血最多」，同一格裡更貴又不更好的必敗，**丟掉是無損的**。
3. **join 用 3-D 後綴最大值表**：把 J 側按價格遞增逐步插入 `T[f][c][l]`，
   對三個軸各做一次 `np.maximum.accumulate`（反向），得到「抗性 ≥ (f,c,l) 的最佳 life」。
   之後每個 A 組只要一次陣列查表。反著跑（把剩餘預算由小到大分箱）就能重用同一張表。

實測：A 側 51 萬組 × J 側 58 萬組，十個預算級距在數分鐘內跑完，而且
**與六層 for 迴圈的暴力解逐級距完全相同**（用小樣本對拍驗過，含「不得重複用同一件」與三抗約束）。
桶截斷版在同一題會少算——A 側被砍 6%、J 側被砍 18%，答案低估 19 點生命。
**寫死的 cap 會安靜地給出次佳解，截頂+Pareto 不會。**

### 但重跑要快：候選瘦身比砍組合數有效得多（使用者要求 2026-07-28）

便宜裝分鐘級售出，交付前常要重算好幾輪，精確解那幾分鐘太久。
**要壓時間就砍「每部位的候選數」，不要砍「組合後的組數」**——前者是平方／立方級的縮減，後者只是線性截斷而且有偏。

瘦身時**取各軸領先者的聯集**（血量前 N、火／冰／雷各前 N、抗性總和前 N、性價比前 N、最便宜前 N），
不要用單一排序的 top-k：只取血量前 k 會把約束需要的高抗件全丟掉，只取抗性前 k 則封死血量上限。

同一題實測（每部位原本 ~120 候選，六部位聯合求解）：

| 每部位保留 | A×J 組數 | 耗時 | 30c 答案 | 15c 答案 |
|---|---|---|---|---|
| 全部（精確） | 51 萬 × 58 萬 | ~4 分鐘 | **985** | **957** |
| 90 | 20 萬 × 17 萬 | 7 秒 | 985 ✅ | 952（−5） |
| **75** | 14 萬 × 11 萬 | **6 秒** | **985 ✅** | 949（−8） |
| 60 | 8 萬 × 7 萬 | 3 秒 | 985 ✅ | 949（−8） |
| 45 | 4 萬 × 4 萬 | 2 秒 | 982（−3） | 949（−8） |
| 35 | 2 萬 × 2 萬 | 2 秒 | 968（−17） | 938（−19） |

**結論：`75` 是好預設——快 40 倍而且頭條（吃滿預算）那一檔與精確解完全相同。**
與本檔前述「headline tiers converge much earlier than mid tiers」一致：**中間級距才是瘦身會掉分的地方**。
首次交付跑精確解，之後每次「有東西被買走→重算」用瘦身版即可。
瘦身後**瓶頸會從求解變成逐件重驗在架**（每件 1 search + 1 fetch），那才是重跑的時間下限。

## The price cap's "equivalent" mode uses a hidden internal rate (等值價格上限用內部匯率)

`trade_filters.price` with the currency **option omitted** doesn't compare literal prices — the server converts every listing into the realm's base currency using GGG's **internal** exchange rate, which can differ a lot from the real market rate. That rate has **no public endpoint**; you can only infer bounds from search behavior (which literally-priced listings pass a given equivalent cap). Measured divergence figures are realm- and league-specific — see the realm's KB.

**Rule:** use the equivalent-mode cap only as a coarse pre-filter (pad it generously), then filter by the **actual listed price** from the fetch API. Alternatively run a literal-currency control query (`{"option": "<currency>", "max": N}`) — it matches only listings priced in that currency, but compares by literal amount, no conversion involved.

For real market rates: never guess, and never use the trade-site exchange **listing board** (a thin manual board with bait listings and wide spreads, not the in-game matching market). Each realm's KB documents its own rate source.
