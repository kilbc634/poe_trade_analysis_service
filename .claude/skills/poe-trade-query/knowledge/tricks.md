# Query tricks & API gotchas (查詢技巧與陷阱)

Hard-won facts about how the search API actually behaves. Check before trusting a filter to do what its name suggests.

## Cloudflare 403 on plain HTTP: it's the User-Agent (純 HTTP 被 CF 擋：UA 是關鍵)

Controlled test 2026-07 against `POST /api/trade2/search`: bare `User-Agent: Mozilla/5.0` → **403 blocked**; full realistic UA (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36`) → **200, even with no cookies at all**. So for anonymous price checks: send a full browser UA and skip the browser entirely.

**Escalation ladder if a plain-HTTP call still gets blocked (user-confirmed policy 2026-07):**
1. Full realistic UA (usually enough — Cloudflare scores a normal UA high).
2. Add cookies from `.poe_cookies.json` (project root, gitignored) — holds `POESESSID`, `cf_clearance`, and the UA they were captured under. `cf_clearance` is bound to **IP + UA**, so always send it with the stored `user_agent` (but it is only needed for the Cloudflare-gated `/data/*` endpoints, NOT search/fetch). Do NOT store POETOKEN (short-lived login-only OAuth JWT, not needed for trade APIs). **A logged-in POESESSID matters for far more than whisper/buy: it puts search/fetch on a SEPARATE, near-unlimited rate-limit pool** — see "The header counters are a DECOY" below. Prefer sourcing it from `setting.py` (env-backed) over the cookie cache for bulk jobs.
3. Still blocked → add full browser-parity headers (template from a real Chrome capture): `accept: */*`, `accept-language`, `origin: https://www.pathofexile.com`, `referer: https://www.pathofexile.com/trade2/search/poe2/{league}`, `x-requested-with: XMLHttpRequest`, `sec-fetch-dest: empty`, `sec-fetch-mode: cors`, `sec-fetch-site: same-origin`, and the `sec-ch-ua*` client-hint family matching the UA (`sec-ch-ua: "Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"`, `sec-ch-ua-mobile: ?0`, `sec-ch-ua-platform: "Windows"`, …).
4. Last resort → open-poe-trade headed browser, let the challenge clear, then go back to plain HTTP.

**Refresh-on-trigger rule:** every time step 4 fires (a headed browser had to clear a challenge), immediately re-export cookies + UA and overwrite `.poe_cookies.json` (playwright: `page.context().cookies('https://www.pathofexile.com')` filtered to POESESSID/cf_clearance, plus `navigator.userAgent`), so the cache always holds the latest known-good clearance.

In-page `fetch` (browser already open) remains a valid alternative to 2–4. Rate-limit etiquette applies on every path: ≤10 hashes per fetch, ~1.7s between fetches, ~2.2s between searches.

## Rate-limit headers: the actual rules (官方限流規則與 header 語義)

Official docs: <https://www.pathofexile.com/developer/docs/index#ratelimits>. Every trade API response carries:

- `X-Rate-Limit-Policy` — policy name (search: `trade-search-request-limit`, fetch: `trade-fetch-request-limit`; per-policy budgets, shared across endpoints with the same policy)
- `X-Rate-Limit-Rules` — active rule dimensions (`Ip`, sometimes `Account`, `Client`)
- `X-Rate-Limit-<Rule>` — comma-list of `max_hits:period_s:penalty_s` (ALL windows apply simultaneously)
- `X-Rate-Limit-<Rule>-State` — same shape: `current_hits:period_s:active_restriction_s` (3rd number >0 = currently locked out)
- On breach: 429 + `Retry-After` (seconds until the restriction expires)

Snapshot 2026-07-08 (dynamic — **reread at runtime, never hardcode**): **search** IP rule `8:10:60, 15:60:120, 60:300:1800`; **fetch** anon IP `12:4:10, 16:12:300`, but authed shows IP `12:4:60, 16:12:60` **plus** `Account 6:4:10`. These numbers drift between readings (search was `5:10:60,15:60:300,30:300:1800` on 07-05) — "limits can change at any time depending on our requirements", and observed `Retry-After` values (600/605s) match no published tuple. Parse the live headers.

**Counters are per-policy** (verified): a fetch hit does not touch the search policy's `-State` and vice versa; the two budgets run in parallel. Within one pool a fired penalty is enforced across ALL trade endpoints (a fetch during a search-triggered lockout still 429s; see the 429 section below).

### The header counters are a DECOY — the real limiter is hidden and login-gated (2026-07-08, the big one)

Measured directly with `ratelog.py` (2.5s spacing, per-request Ip-State logged). This overturns the old "just obey the headers" strategy:

- **Anonymous fetch has an UNDOCUMENTED hidden quota.** The visible `X-Rate-Limit-Ip-State` sat steady at `2:4:0, ~5:12:0` — nowhere near the `12`/`16` caps — for **32 straight 200s, then request #33 returned 429 `Retry-After: 600` with NO `X-Rate-Limit-*` headers at all**. So `_throttle_wait()` (reacts only to visible near-cap counters) is **structurally blind** to what actually penalizes you. This is why bulk anon runs hit ~600s walls "for no reason" every ~30 requests. It is count-based over a multi-minute rolling window, not rate-based — slower spacing (6s vs 2.5s) only delays the wall. Anon fetch throughput is hard-capped ≈30 fetches / ~10 min.
- **Authenticated (POESESSID) is a SEPARATE pool with no such wall.** Same endpoint/IP/instant: anon → 429 locked, authed → 200 clean. Authed adds an `Account` dimension (`Rules=Account,Ip`); crucially **even its `Ip` counter reads clean** while the anon `Ip` is locked — GGG keys the bucket on (IP × identity), so an anon IP penalty does NOT touch authed traffic. A 50-fetch back-to-back authed run hit **zero** penalties (anon died at 33). The hidden quota does not apply to logged-in traffic (or is far higher — untested past 50).
- **Practical rule: always send a logged-in POESESSID for bulk work.** `gear_combo_optimizer.py` reads it from `setting.py` by default and refuses to run anonymously unless `--anon` is passed (tiny jobs only). The 32-hex `POESESSID` authenticates search/fetch; `cf_clearance` is NOT needed for these (only `/data/*` is Cloudflare-gated). Detect an expired POESESSID at runtime: a cookie'd request coming back with `Rules=Ip` (no `Account`) did not authenticate → refresh it.
- **Anti-rapid-click is yet another separate layer.** ~4 requests in ~2s returns 429 "wait 60s" while the visible state is only `4:10:0` (far below cap) — a burst guard the headers can't predict. Fixed inter-request floors are what prevent it, NOT the header logic.
- **Measured floor (authed pool, 2026-07-08, user-requested speed test): search 2s + fetch 1.5s is SAFE** when combined with the header-adaptive `_throttle_wait()`. A full 33-search / ~190-fetch-batch authed run at that pace hit **zero 429s**. Mechanics: at 2s the search window nears cap every ~2 POSTs and the throttle inserts a 5s wait (so effective search pace self-caps ~3.5s — faster fixed pacing than 2s buys nothing); fetch at 1.5s ran clean throughout, so the old 2.5s fetch floor was conservative. The floors only guard bursts; the adaptive throttle does the real work. (Anon pool untested at this pace — its hidden quota walls you anyway.)

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

A search response stores **up to 100 result hashes**. Since results sort by price asc, hashes `[40:100]` are the *more expensive tranche* of the same query — fetch them directly with the same `query_id`, no new search POST needed. Ideal when the cheap end is exhausted and you want to see what more budget buys (price/quality frontier) without spending search-rate budget.

## Probe the ceiling BEFORE building pools (先探頂再撈池, user-taught 2026-07)

Don't jump straight to the pooling script with guessed thresholds — cheap-end-sorted pools make every budget tier collapse to the same cheap answer (sampling bias), which under-serves a "best within budget X" request. First run a few **interactive probe searches** per slot to learn what the top end looks like:

1. Assume the extreme: one slot eating ~80% of the total budget. Add a price cap at ~80% of budget (use `{"option":"divine","max":N}` literal mode — the equivalent-mode internal rate is unreliable) and crank the stat mins up.
2. Read the `total` count from the search response (no fetch needed). **>200 results ⇒ conditions too conservative — raise the stat mins**; near-0 ⇒ back off. Iterate to find where the mod ceiling sits for that slot & budget.
3. Only then define the pool searches around those discovered ceilings (a high-end pool + a mid pool per slot), fetch, and optimize.

The 80% / 200-count numbers are heuristics, not rules — judge from actual counts. And when reporting: the user's "best in budget" means **max score while spending up to the budget**; the CP sweet spot is supplementary info, not the answer.

## Multi-slot gear combos: pool per slot, optimize locally (多部位配裝法)

For "buy N pieces within budget X satisfying joint constraints (total res / total Spirit / …)": don't encode the joint constraints into any single search. Per slot run 2–3 searches (a cheap broad pool + a high-spec pool), fetch ~40 each, parse into normalized candidates (price→div, ES from `extended.es`, res/attr/mana/Spirit via regex on cleaned mod text — strip `[A|B]`→`B`), then brute-force the slot cross-product locally (100³ combos is instant). Report the best combo per budget tier — the marginal-value curve (e.g. 60d→1633, 100d→1646) tells the user where spending stops paying.

**Bucket-cap accuracy: convergence-test it, don't trust one cap.** The staged combine's bucket pruning (`prune_groups`) is the only lossy step vs full brute force (which is ~6.6e12 pairs for 6 slots = months — not an option). Measured sweep on the 2026-07 six-slot case (pure Python, desktop): cap 4000 ≈ 1 min but lost 0.6% on one mid tier; cap 20000 ≈ 2 min, small residual loss; **cap 50000 = 89 s and converged** (identical answers at 100k/14 min and 200k/45 min, the latter being fully-saturated finest-granularity bucketing — an effective no-loss backstop). The headline tiers (sweet spot / max budget) were already exact at cap 4000. Practice: default 50000; for a final deliverable rerun with cap doubled — if nothing changes, call it converged. Kept-counts saturate at the finest bucket pass (here armour 84k, jewelry 157k), so caps beyond that change nothing.

**Reusable implementation: [`scripts/gear_combo_optimizer.py`](../scripts/gear_combo_optimizer.py)** (self-contained stdlib script, 6-slot proven: disk-cached 429-aware search/fetch, mod parser with all known gotchas incl. ring/belt mana-quality conversion, staged combine with bounded bucket pruning + bounded-heap join). Don't rewrite from scratch — copy it to the scratchpad, refresh `CURRENCY_RATES` from [exchange-rates.md](exchange-rates.md), edit CONFIG/SEARCHES/constraints for the task (pool thresholds from ceiling probes first!). Scaling warning baked into the script: windowed Pareto checks and unbounded combo accumulation OOM at 6 slots — keep `prune_groups()` and the heap join as-is.

**Default output rule (user-confirmed 2026-07):** for price checks, do NOT navigate the browser to the results page — just give the user the `https://www.pathofexile.com/trade2/search/poe2/{league}/{query_id}` URL(s) to copy. This holds even when a browser happens to be open. Only `goto` the results page when the user explicitly asks to see it.

## Price cap in exalted-equivalent mode diverges from market rate (等值價格上限的匯率偏差)

`trade_filters.price` with **option omitted** converts every listing to exalted-equivalent using GGG's **internal** exchange rate — which can differ a lot from the real market rate. The internal rate has **no public endpoint**; you can only infer bounds from search behavior (which literally-priced listings pass a given equivalent cap). Observed 2026-07 (Runes of Aldur): a `max: 17000` cap let through items priced up to 52 div → internal rate ≤ ~327 ex/div (upper bound only; bisect the cap if a precise value ever matters), while the true traded rate was ~710 ex/div. So the equivalent-mode cap can be off by >2×.

For actual market rates (div/ex/chaos conversions), see **[exchange-rates.md](exchange-rates.md)** — poe2scout SnapshotPairs is the reliable source; the trade-site exchange listing board is not.

**Rule:** use the equivalent-mode cap only as a coarse pre-filter (pad it generously), then filter by the **actual listed price** from the fetch API. Alternatively run a `{"option":"divine","max":N}` control query — it matches only divine-priced listings but compares by literal divine amount, no conversion involved.

## `equipment_filters.es` (and ar/ev) is the max-quality value (防禦數值按滿品質計)

Defence min/max filters compare against base + local mods **+ 20% quality**, not the item's current sheet value. A search for `es >= 600` can return items currently showing ES ~500 (needs quality currency to reach 600). When reporting results, flag items whose current value is below the user's threshold.

## Fetch API mod entries are mixed string/object (詞綴回傳格式不一)

`item.explicitMods` etc. can contain plain strings **or** objects `{description, hash, mods:[{name, tier, level, magnitudes}]}`. Normalize with `typeof m === 'string' ? m : m.description`. Bonus: the object form's `tier`/`magnitudes` tells you the mod's tier and roll range — useful for judging whether a roll is near its cap without leaving the result set.

More fetch-parsing facts (2026-07):
- Mod text embeds wiki-link brackets: `+12 to [Spirit|Spirit]`, `[EnergyShield|Energy Shield]` — strip with regex `\[([^\[\]|]*\|)?([^\[\]]*)\]` → `\2` before matching.
- Crafted mods appear **inside `explicitMods`** with `flags: {crafted: true}` (hash `stat.crafted.…`), not in a separate `craftedMods` array.
- The item's current defence numbers live in `item.extended` (`es`, `ev`, `ar`) — no need to parse `properties`.
- `runeMods` starting with `Bonded:` (raw tag `[ShamanOnlyMods|Bonded]`): **Bonded is not a rune type** — the Shaman ascendancy gains extra effects from every socketed rune, and the `Bonded:` line is that extra effect. The same rune's *normal* effect appears as its own separate line (and defence-type effects are already baked into `extended.es`). Scoring rule: for non-Shaman buyers exclude only the `Bonded:` lines and count everything else as usual; the sockets are NOT wasted — they hold normally-working runes.
- **Corrupted items CAN swap runes** (user-confirmed 2026-07): corruption locks the *number* of rune sockets, not their contents. So when valuing a corrupted item, treat every rune socket as "replaceable with the best rune for the build" — a bad rune (e.g. a useless Bonded) is not dead weight, but a *missing* socket can never be added. What corruption does forbid: further crafting/modification and adding quality.

*(learned 2026-07 during a Spirit+ES chest price hunt)*
