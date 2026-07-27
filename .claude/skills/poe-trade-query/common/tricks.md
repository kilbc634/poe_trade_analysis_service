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

**Refresh-on-trigger rule:** every time step 4 fires (a headed browser had to clear a challenge), immediately re-export cookies + UA and overwrite `.poe_cookies.json` (playwright: `page.context().cookies('https://www.pathofexile.com')` filtered to POESESSID/cf_clearance, plus `navigator.userAgent`), so the cache always holds the latest known-good clearance.

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
- **Practical rule: always send a logged-in POESESSID for bulk work.** `gear_combo_optimizer.py` reads it from `setting.py` by default and refuses to run anonymously unless `--anon` is passed (tiny jobs only). The 32-hex `POESESSID` authenticates search/fetch; `cf_clearance` is NOT needed for these (only `/data/*` is Cloudflare-gated). Detect an expired POESESSID at runtime: a cookie'd request coming back with `Rules=Ip` (no `Account`) did not authenticate → refresh it.
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

## Multi-slot gear combos: pool per slot, optimize locally (多部位配裝法)

> **Method skeleton only.** The scoring function, which stats you parse out, the currency, the mod-text format, and every measured number are **game-specific** — get them from `<realm>/knowledge/`.

For "buy N pieces within budget X satisfying joint constraints (some total across the whole set)": **don't try to encode the joint constraints into any single search** — the site can't express them. Instead:

1. **Per slot**, run 2–3 searches: a cheap broad pool + a mid pool + a high-spec pool at the probed ceiling (thresholds from the ceiling probes above, never guessed). Price asc.
2. **Fetch ~40 per search**, plus the deep-fetch tranche when you want the expensive end.
3. **Parse into normalized candidates** — price converted to one currency, plus whatever stats the build's scoring function needs. Mod-text parsing rules are realm-specific; see the realm's KB.
4. **Brute-force the slot cross-product locally.** Small cases (100³) are instant; more slots need the staged combine below.
5. **Report the best combo per budget tier.** The marginal-value curve is the real deliverable — it shows the user where spending stops paying.

**Bucket-cap accuracy: convergence-test it, don't trust one cap.** In the staged combine, bucket pruning (`prune_groups`) is the only lossy step versus full brute force (astronomically large at 6 slots — not an option). Practice: **default cap 50000; for a final deliverable rerun with the cap doubled — if the answers don't change, call it converged.** Kept-counts saturate once bucketing reaches its finest granularity, and caps beyond that point change nothing; that saturation point is case-specific, so measure it rather than assuming. Headline tiers (sweet spot / max budget) converge much earlier than mid tiers.

**Reusable implementation: [`../scripts/gear_combo_optimizer.py`](../scripts/gear_combo_optimizer.py)** (self-contained stdlib script, 6-slot proven: disk-cached 429-aware search/fetch, mod parser, staged combine with bounded bucket pruning + bounded-heap join). **Its endpoint paths, filter field names, mod regexes and scoring are a POE2 profile** — see the script header before using it on POE1. Don't rewrite from scratch — copy it to the scratchpad, refresh the currency rates from the realm's exchange-rate notes, edit CONFIG/SEARCHES/constraints for the task (pool thresholds from ceiling probes first!). Scaling warning baked into the script: windowed Pareto checks and unbounded combo accumulation OOM at 6 slots — keep `prune_groups()` and the heap join as-is.

**Default output rule (user-confirmed 2026-07):** for price checks, do NOT navigate the browser to the results page — just give the user the search-result URL(s) to copy (build them per the realm's QUERY.md). This holds even when a browser happens to be open. Only `goto` the results page when the user explicitly asks to see it.

## The price cap's "equivalent" mode uses a hidden internal rate (等值價格上限用內部匯率)

`trade_filters.price` with the currency **option omitted** doesn't compare literal prices — the server converts every listing into the realm's base currency using GGG's **internal** exchange rate, which can differ a lot from the real market rate. That rate has **no public endpoint**; you can only infer bounds from search behavior (which literally-priced listings pass a given equivalent cap). Measured divergence figures are realm- and league-specific — see the realm's KB.

**Rule:** use the equivalent-mode cap only as a coarse pre-filter (pad it generously), then filter by the **actual listed price** from the fetch API. Alternatively run a literal-currency control query (`{"option": "<currency>", "max": N}`) — it matches only listings priced in that currency, but compares by literal amount, no conversion involved.

For real market rates: never guess, and never use the trade-site exchange **listing board** (a thin manual board with bait listings and wide spreads, not the in-game matching market). Each realm's KB documents its own rate source.
