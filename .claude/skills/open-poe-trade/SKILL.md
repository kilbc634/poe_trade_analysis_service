---
name: open-poe-trade
description: Open the Path of Exile official trade website in a browser, logged-in, by injecting the POESESSID cookie (skips the login form and its captcha). Use this whenever a task needs the POE trade site open — inspecting listings, capturing payloads, driving searches, or any follow-up trade automation. Also provides background concepts about how POE trade (POE1/POE2) works.
allowed-tools: Bash(playwright-cli:*) Bash(npx:*) Read Grep
---

# Open the PoE Trade site (cookie-injected login)

This skill gets the Path of Exile trade website open **and logged in**, ready for whatever the user wants to do next. It relies on the companion **`playwright-cli`** skill for the actual browser mechanics — load that skill's commands for anything beyond what's shown here.

Logging in with account+password triggers a Cloudflare captcha and is fragile. Instead we **inject the `POESESSID` session cookie** to appear already-logged-in, and let a real (headed) browser clear Cloudflare's bot check on its own.

---

## Background: how PoE trade works (just enough to be useful)

- **Two games, one site.** POE1 lives under `/trade/…`; POE2 under `/trade2/…` with an extra `poe2` realm segment. This project switches via `REALM` (`poe1` / `poe2`) and `LEAGUE` (e.g. `Runes of Aldur`) in `setting.py`.
- **Saved search = `query_id`.** A search is saved server-side and referenced by a short code in the URL, e.g. `…/trade2/search/poe2/Runes%20of%20Aldur/bZaKgmRSL`. The trailing code is the `query_id`.
- **The HTML pages are behind Cloudflare** (a "請稍候…/正在執行安全驗證" managed challenge). A real headed browser solves it automatically and gets a `cf_clearance` cookie; headless is often blocked.
- **The JSON API under `/api/…` is NOT behind that JS challenge** — plain HTTP (httpx/requests) with just the `POESESSID` cookie works. What each endpoint does (paths per realm are in the routing table below):
  - **search** (POST, body `{query, sort}`) → `{id, result:[hashes], total}`
  - **retrieve a saved query** (GET, search path + `/{query_id}`) → `{id, query}` — works even without login, and even for other people's query_ids
  - **fetch** (GET, `…/fetch/{ids}?query={query_id}`) → listing details (price, `stash.x/y`, `hideout_token` or `whisper_token`)
  - **whisper** (POST, body `{token}`) → makes your in-game character travel to the seller's hideout (requires being online in-game)
  - **live search** (websocket) → pushes new listings as they're listed. **這個 skill 不做 live search** —— 使用者要即時監控時走現成的 `script/scavenger.py`（已支援兩個 realm），或就讓他在 UI 上開。

### Realm routing table (POE1 `/trade` vs POE2 `/trade2`)

Build every URL from this table using `REALM` + `LEAGUE` from `setting.py` — **never hardcode one realm's path**. URL-encode the league (spaces → `%20`).

| | **POE1** (`REALM=poe1`) | **POE2** (`REALM=poe2`) |
|---|---|---|
| 交易頁 | `/trade/search/{league}` | `/trade2/search/poe2/{league}` |
| 搜尋 POST | `/api/trade/search/{league}` | `/api/trade2/search/poe2/{league}` |
| 取回已存查詢 | `/api/trade/search/{league}/{query_id}` | `/api/trade2/search/poe2/{league}/{id}?realm=poe2` |
| fetch | `/api/trade/fetch/{ids}?query={id}` | `/api/trade2/fetch/{ids}?query={id}&realm=poe2` |
| whisper / 前往藏身處 | `/api/trade/whisper`，body `{"token": "<JWT>"}` | `/api/trade2/whisper` |
| live websocket | `wss://www.pathofexile.com/api/trade/live/{league}/{id}` | `wss://www.pathofexile.com/api/trade2/live/poe2/{league}/{id}` |
| localStorage 狀態 key | `lscache-tradestate`（值的形狀 `{league, status}`，**沒有** `realm` 欄位） | `lscache-trade2state`（`{realm, league, status}`） |
| 聯盟名範例 | `Allflame`（2026-07 當期） | `Runes of Aldur` |

**POE1 側已於 2026-07-27 逐格實測**（authenticated）。除了 API 直打，也在 UI 按下 Search 並攔截 `fetch`/`XHR`，確認前端打的就是這張表上的路徑（`XHR POST /api/trade/search/Allflame`）；live search 也實際掛了 60 秒收到 10 筆推播。結論：

- **POE1 的路徑裡完全沒有 realm 區段，也不需要 `?realm=` 參數** —— search / 取回查詢 / fetch 三者裸路徑直接回 200。加 `/pc/` 反而會失敗（live websocket 的 `/api/trade/live/pc/{league}/{id}` 變體實測 ERROR，不帶 `pc` 才 OPEN）。**POE2 URL 裡的 `poe2` 區段和 POE1 的 `realm` 概念無關**，別互相套用。
- **fetch 一次上限 10 個 hash，跟 POE2 相同**：11 個回 `HTTP 400 {"error":{"code":2,"message":"Invalid query"}}`。搜尋回應一樣存 100 個 hash。
- **`status` 選項兩邊完全相同**：`available`（Instant Buyout and In Person）/ `securable`（Instant Buyout）/ `onlineleague` / `online` / `any`。所以 `securable` 在 POE1 有效，b2 步驟的 seeding 實測有效（重載後下拉顯示 Instant Buyout）。
- **whisper 已驗證**（2026-07-27，角色離線時點掛單的 **Travel to Hideout**）：`POST /api/trade/whisper`，body `{"token":"<JWT>"}`，**走 XHR 不是 `fetch`** —— 要攔截頁面請求時兩種都得掛，只包 `window.fetch` 會什麼都錄不到、看起來像按鈕沒反應。角色離線回 `400 {"code":2,"message":"Invalid query; Your account must be in-game to use this feature"}`，不會送出任何東西給賣家；**線上時會真的執行**，別拿線上帳號亂點。
- 掛單上的動作按鈕**會過期**：放置一段時間後 `button.direct-btn` 變 `disabled`、title 顯示 `Item must be refreshed`，要重按一次 Search 換新 token 才能點。

> **限流是跨遊戲共用的（2026-07-27 實測確認）。** 同一把 POESESSID 交錯打兩款遊戲的 search，`X-Rate-Limit-Policy` 都是 `trade-search-request-limit`，且 `X-Rate-Limit-Ip-State` 的計數是連續累加的：POE1 → `11:10800`、POE2 → `12:10800`、POE1 → `13:10800`。**所以狂打 POE2 會把 POE1 一起鎖住**，配額要當成一個池來規劃。實測當下的規則：search IP `8:10:60,15:60:120,60:300:1800,600:10800:3600` + Account `3:5:60`；fetch IP `12:4:60,16:12:60,100:300:300,1000:10800:1800`。（數值會漂，一律 runtime 讀 header。）

> ⚠ `setting.py` 只有**單一個 `LEAGUE`**，兩款遊戲共用這一格。只改 `REALM` 沒改 `LEAGUE` 的話，會拿另一款遊戲的聯盟名去打端點——通常**回空結果而不是報錯**，非常難查。兩者永遠成對修改。
>
> ⚠ 遊戲知識（stat id、篩選欄位名、詞綴、行情）**不在這個 skill 裡**，也不准跨遊戲沿用。那些在 `poe-trade-query` skill 的 `poe1/` 與 `poe2/` 目錄，各自獨立。
- **Auth cookies.** `POESESSID` = the session (what we inject). After a real login the site also sets `POETOKEN` (a ~24h OAuth JWT) and `cf_clearance`; for opening the trade site logged-in, `POESESSID` in a Cloudflare-cleared browser is enough.
- **Rate limits — read the headers, and watch the IP rule only.** POE returns the current limit state in every response's headers, and GGG can change the limits at any time, so read them at runtime rather than hardcoding intervals. In practice only the **IP** rule matters (it caps first):
  - `X-Rate-Limit-Rules` — which rules are active (e.g. `Ip,Account`).
  - `X-Rate-Limit-Ip` — the IP limits, one or more `hits:period:restrict` tuples (multiple time windows, comma-separated). Example `8:10:60,15:60:120` = max 8 per 10s **and** 15 per 60s, with a 60s/120s lockout if violated.
  - `X-Rate-Limit-Ip-State` — same shape, but the first number is the **current** hits used in that window (how close you are to the cap).
  - On breach: HTTP **429** + `Retry-After` (seconds to wait).
  - So: keep `-State` below `X-Rate-Limit-Ip`, and `sleep(Retry-After)` on a 429. Docs: <https://www.pathofexile.com/developer/docs#ratelimits>
- **Other gotchas.** A fetched listing with `"gone": true` was just sold. `status.option = "securable"` means "Instant Buyout".

---

## Step 1 — Get the POESESSID

1. Read `setting.py` and look at the `POESESSID` line:
   ```
   POESESSID = os.getenv('POESESSID', '<default>')
   ```
   (grep it: `POESESSID = os.getenv` in `setting.py`.)
2. If the default (the 2nd argument) is a **non-empty** string, use it.
3. If it is empty (`''`), **ask the user for their POESESSID** — do not guess. Explain it's the `POESESSID` cookie from a logged-in pathofexile.com session (found via browser dev tools → Application → Cookies). Treat it as a secret: don't echo it back or commit it into `setting.py`.

Also read `REALM` and `LEAGUE` from `setting.py` to build the correct URL (defaults: `poe2` / `Runes of Aldur`).

## Step 2 — Open the site, injected & logged in

Use `playwright-cli` (headed, so Cloudflare auto-clears). Build the trade URL from `REALM`/`LEAGUE` **via the realm routing table above** (URL-encode the league; spaces → `%20`). The league values shown in the commands below are examples — substitute what `setting.py` actually says.

```bash
# a) open a real (headed) browser at the homepage first — clears Cloudflare + establishes the cookie domain
playwright-cli open --headed "https://www.pathofexile.com/"

# a2) maximize the window (headed windows don't open maximized; maximizing makes the page clearer & avoids element distortion)
playwright-cli run-code "async page => { const c = await page.context().newCDPSession(page); const {windowId} = await c.send('Browser.getWindowForTarget'); await c.send('Browser.setWindowBounds', {windowId, bounds:{windowState:'maximized'}}); }"

# b) inject the session cookie (skips the login form)
#    NOTE: do NOT pass --path=/ — playwright-cli 0.1.14 rejects it ("Invalid cookie fields"); path defaults to / anyway.
playwright-cli cookie-set POESESSID <POESESSID> --domain=.pathofexile.com --httpOnly --secure

# b2) pre-select "Instant Buyout" as the default status. The trade site persists the status dropdown in a
#     localStorage key (per the routing table); seeding it means a fresh trade page (no query_id) opens on
#     Instant Buyout instead of "Any". Use the key/realm/league for YOUR realm — pick ONE of the two below.

#     REALM=poe2:
playwright-cli --raw eval "localStorage.setItem('lscache-trade2state', JSON.stringify({realm:'poe2', league:'Runes of Aldur', status:'securable'}))"
#     REALM=poe1 (verified 2026-07-27; note there is NO realm field in the POE1 shape):
playwright-cli --raw eval "localStorage.setItem('lscache-tradestate', JSON.stringify({league:'Allflame', status:'securable'}))"

# c) go to the trade search page — again, ONE of the two, matching setting.py:
#     REALM=poe2:
playwright-cli goto "https://www.pathofexile.com/trade2/search/poe2/Runes%20of%20Aldur"
#     REALM=poe1:
playwright-cli goto "https://www.pathofexile.com/trade/search/Allflame"

# d) verify logged-in (prints the account name, or SIGN-IN-REQUIRED / the current title)
playwright-cli --raw eval "(()=>{const a=document.querySelector('a[href*=\"view-profile\"]'); return a?('LOGGED-IN '+a.textContent.trim()):(document.body.innerText.includes('Sign in')?'SIGN-IN-REQUIRED':'TITLE='+document.title);})()"
```

> `status:"securable"` = Instant Buyout — **verified on both realms** (2026-07-27); the full option set is identical across POE1/POE2. In practice you almost never want any other mode, so seeding it up front avoids forgetting to switch later. The dropdown will show **Instant Buyout** once the trade page loads.

Expected: step (d) returns `LOGGED-IN <account>#####`.

## Step 3 — Handle Cloudflare if it lingers

- If a page's title is `請稍候...` or it shows **"正在執行安全驗證"**, the Cloudflare challenge hasn't cleared yet. It only appears on the trade page (not the homepage) and a real headed browser clears it on its own, typically within ~5s. Poll with the lightweight `playwright-cli --raw eval "document.title"` every few seconds until it stops being `請稍候...` (lighter than a full `snapshot`).
- If it still won't pass, ask the user to click through the challenge in the **visible browser window**, then continue.
- If step (d) says `SIGN-IN-REQUIRED`, either the cookie didn't take or the session is invalid. **Recover by `goto`-ing the clean trade URL again, not `reload`** — after the Cloudflare challenge the URL can keep a `?__cf_chl_f_tk=…` token and `reload` re-requests that stale token URL.
- **Confirm login / detect expiry authoritatively — probe an authed endpoint (and don't loop):**
  ```bash
  playwright-cli --raw eval "(async()=>{const r=await fetch('/api/profile');return r.status})()"
  ```
  **200** = logged in; **401** = the POESESSID is not an authenticated session. Note POESESSID **also exists when logged out**, so a well-formed 32-char value can still be anonymous (and the server won't necessarily replace it — this session just fails auth). On 401, re-injecting won't help — ask the user for a POESESSID from a **currently logged-in** pathofexile.com session (confirm the account name shows top-right first; logging in rotates the value), then update `setting.py` / the env var. You can also pre-validate a POESESSID from the shell without a browser: `GET https://www.pathofexile.com/api/profile` with header `Cookie: POESESSID=<value>` → 200 vs 401.

## Tips

- **Persist across runs:** add `--persistent` to `open` (e.g. `playwright-cli open --headed --persistent "https://www.pathofexile.com/"`). The profile keeps `cf_clearance` + login, so later runs skip Cloudflare and re-injection.
- **Prefer the API when you don't need the UI.** For reading/searching listings, the `/api/…` endpoints work with plain `httpx`/`requests` + `POESESSID` (no browser, no Cloudflare). Only open the browser when the task genuinely needs the rendered page or in-page interaction.
- Once open, use the `playwright-cli` skill's `snapshot` / `click` / `fill` / `eval` commands to drive the page.
