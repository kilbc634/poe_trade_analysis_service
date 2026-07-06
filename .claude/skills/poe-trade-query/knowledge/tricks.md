# Query tricks & API gotchas (查詢技巧與陷阱)

Hard-won facts about how the search API actually behaves. Check before trusting a filter to do what its name suggests.

## Cloudflare 403 on plain HTTP: it's the User-Agent (純 HTTP 被 CF 擋：UA 是關鍵)

Controlled test 2026-07 against `POST /api/trade2/search`: bare `User-Agent: Mozilla/5.0` → **403 blocked**; full realistic UA (`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36`) → **200, even with no cookies at all**. So for anonymous price checks: send a full browser UA and skip the browser entirely.

**Escalation ladder if a plain-HTTP call still gets blocked (user-confirmed policy 2026-07):**
1. Full realistic UA (usually enough — Cloudflare scores a normal UA high).
2. Add cookies from `.poe_cookies.json` (project root, gitignored) — holds `POESESSID`, `cf_clearance`, and the UA they were captured under. `cf_clearance` is bound to **IP + UA**, so always send it with the stored `user_agent`. POESESSID is only needed for authed actions (whisper/direct-buy); anonymous sessions get a POESESSID too, so its presence ≠ logged in. Do NOT store POETOKEN (short-lived login-only OAuth JWT, not needed for trade APIs).
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

Snapshot 2026-07-05 (IP rule): search `5:10:60, 15:60:300, 30:300:1800` — note the third window: >30 searches in 5 min = **30-minute lockout**. Fetch `12:4:10, 16:12:300`.

Key facts from the docs + observation:
- **Limits are dynamic** — "can change at any time depending on our requirements". Observed Retry-After values (605s) that match none of the published tuples, presumably stricter load-dependent rules. So parse headers at runtime; never trust hardcoded intervals alone.
- **"Exceeding these limits frequently will result in your application access being revoked"** — proactive header-driven throttling (stay below `max-1`, honor active restrictions in `-State`) beats sleep-the-penalty as a strategy. `gear_combo_optimizer.py` `req()` implements this.

## Rate-limit penalties are long and shared (429 懲罰期長且全 API 共用)

Observed 2026-07 doing bulk multi-search work: the **search POST budget is small** — ~7 searches at 2.2s spacing passed, but continuing to ~11 within a minute triggered a 429 with `Retry-After: 472` (~8 min!), and a later fetch-stage 429 said 605s. Key facts:
- **The penalty blocks ALL trade API endpoints** (search *and* fetch), not just the violated one. Don't try to "use the other endpoint meanwhile" — a fetch during the penalty just hangs on 429s.
- **Never retry during the penalty.** Each blocked request risks re-extending it. Sleep the full `Retry-After` + a few seconds, then resume.
- For bulk sessions (many searches), space searches **~30s apart** — that spacing survived 4+ consecutive searches repeatedly. Fetches at 2.5s spacing are mostly safe but still honor any 429's `Retry-After` exactly.
- **The fetch budget is a rolling window of roughly 25–30 batches regardless of spacing** (observed 2026-07: 429+605s hit after ~14–30 batches at both 2.5s and 6s spacing, especially right after a 15-search burst). For 60+ batch jobs, budget for one 605s penalty per ~25 batches — or plan pools so the must-have data comes first. Cache every search + every fetched batch to disk keyed by (search, range) so a killed/crashed run resumes free.
- Long waits → run the whole resume plan as one background script with 429-aware retry (read `Retry-After`, sleep, retry once), not as foreground calls that time out mid-wait.

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
