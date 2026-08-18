> **Realm-agnostic** — this format applies to POE1 and POE2 alike. Keep it free of game-specific stats, currencies and field names.

# Deliverable format for gear-search results (配裝查詢交付標準, user-defined 2026-07)

Chat output gets scrolled away — final gear recommendations MUST be delivered as a file, not only as a chat message.

## The standard

Write `search_results_<YYYYMMDDHHmm>.md` in the **project root** (timestamp = generation time). Structure:

1. **Header**: league, the user's constraints, budget, exchange-rate reference, generation time.
2. **One section per recommended combo** (top/max-budget combo first; CP sweet spot as an additional section when it differs meaningfully). Each section has, **as a bullet list (`- **欄位**: …` — consecutive bold lines without bullets merge into one paragraph in markdown)**:
   - **描述** — one or two sentences on what makes this combo tick
   - **總價格** (+ the combo's score under whatever scoring function the build uses)
   - **需求檢核** — achieved vs required for **every** constraint the user gave, flag anything at/near the limit
   - **驗證在架** — when each listing was last verified live (stale timestamps = warn)
   then the **Table** with columns: 部位 | 名稱 | 關鍵屬性 | 價格 | 購買連結 | 備註
3. **通用注意事項** footer: near-limit stats, quality/catalyst assumptions, what to do if an item sells out.

Table rules:
- 購買連結 = markdown hyperlink (`[打開](url)`) to a **seller-account-filtered** search (build with `trade_filters.account`), so no seller column is needed. **The account name must carry its `#1234` discriminator** — dropping it returns 0 results silently, not an error. Copy `listing.account.name` from the fetch response verbatim; the exact value shape and the results-page URL format are per-realm — see the realm's QUERY.md.
- If the seller-filtered search matches >1 item, say so in 備註 with how to identify the right one (price + base name).
- 備註 also carries: corrupted status, "shared with combo X" for overlapping items, buy-priority hints (high-CP items sell fast — buy first), catalyst/quality to apply after purchase.

## Why file > chat

User feedback 2026-07: direct chat delivery gets missed or washed away by later messages, and the assistant itself may forget the links in later turns. A timestamped file in the project root is re-openable, clickable in any markdown viewer, and survives the session.

## ⚠ These files are DISPOSABLE — never cite one from the knowledge base (2026-08-17)

`search_results_*.md` is gitignored at the project root, i.e. **untracked scratch output**. Any given file
may be deleted, or simply never have existed in a fresh checkout. So:

- **Never link to a specific `search_results_<timestamp>.md` from a `knowledge/` file or from `QUERY.md`** —
  it becomes a dead link the moment the scratch file is cleaned up. Record the **format** in the KB, not a filename.
- Conversely, the deliverable itself is still the right place for the volatile stuff (live prices, query_ids,
  seller links). Durable method and measured *shapes* go to `knowledge/`; the disposable snapshot goes to the file.
