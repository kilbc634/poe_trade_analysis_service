# poe_trade_analysis_service

`setting.py` 在版控裡，所以 POE trade API 的 session cookie 不放在它的 getenv 預設值，
而是放在專案根目錄的 `.poesessid`（單行純文字，已 gitignore）。貼進 `setting.py` 的 token 會由
`.claude/hooks/vacuum_poesessid.py` 在下一次送出訊息時搬進去，那一格因此永遠是空的。

怎麼取用、失效了怎麼處理，寫在 `.claude/skills/`：`open-poe-trade` 的 Step 1 與
`poe-trade-query/common/tricks.md`。
