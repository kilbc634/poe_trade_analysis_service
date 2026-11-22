import os
import re

REDIS_HOST = os.getenv('REDIS_HOST', '172.17.0.1')
REDIS_AUTH = os.getenv('REDIS_AUTH', 'cv*****')
BROKER_URL = os.getenv('BROKER_URL', f'redis://:{REDIS_AUTH}@{REDIS_HOST}:6379/0')
# ↑ REDIS_* / BROKER_URL 只有已棄用的雲端 payload 服務（app.py）在用。

# POESESSID 來源順序：環境變數 → 專案根目錄的 .poesessid（單行純文字，已 gitignore）。
# 本檔在版控裡，所以預設值必須永遠留空。手貼進下面那個引號的 token 會被
# .claude/hooks/vacuum_poesessid.py 在下次送出訊息時搬進 .poesessid 並清空這裡。
POESESSID = os.getenv('POESESSID', '')
if not POESESSID:
    _poesessid_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.poesessid')
    try:
        with open(_poesessid_file, encoding='utf-8') as _f:
            POESESSID = _f.read().strip()
    except OSError:
        pass
# 查詢 id 有兩個來源，合併後去重（保留順序）：
#   QUERY_IDS      逗號分隔的一串（也容忍空白 / 換行）
#   QUERY_ID_<n>   一格一個（Jenkins 上是 QUERY_ID_1 ~ QUERY_ID_10），依 n 由小到大接在後面
# id 本身是 base64url，不含空白與逗號。多行值過不了 Jenkins 的 docker 外掛（只剩第一行），所以才拆成多格。
def _split_ids(raw):
    return [x for x in re.split(r'[\s,]+', raw) if x]

QUERY_IDS_RAW = os.getenv('QUERY_IDS', '')
_numbered = sorted(
    (int(m.group(1)), v) for k, v in os.environ.items()
    if (m := re.fullmatch(r'QUERY_ID_(\d+)', k))
)
QUERY_IDS = list(dict.fromkeys(
    _split_ids(QUERY_IDS_RAW) + [x for _, v in _numbered for x in _split_ids(v)]
))

# 交易站 realm：'poe1' 或 'poe2'
REALM = os.getenv('REALM', 'poe1')
# 聯盟名稱，必須與 REALM 成對修改（POE1 例：Covens；POE2 例：Runes of Aldur）
# 只改 REALM 忘了改 LEAGUE 會拿另一款遊戲的聯盟名去打端點，通常回空結果而非報錯
LEAGUE = os.getenv('LEAGUE', 'Covens')
