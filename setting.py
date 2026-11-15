import os

REDIS_HOST = os.getenv('REDIS_HOST', '172.17.0.1')
REDIS_AUTH = os.getenv('REDIS_AUTH', 'cv*****')
BROKER_URL = os.getenv('BROKER_URL', f'redis://:{REDIS_AUTH}@{REDIS_HOST}:6379/0')
SERVICE_HOST = os.getenv('SERVICE_HOST', 'http://tsukumonet.ddns.net:16666/')

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
QUERY_IDS_RAW = os.getenv('QUERY_IDS', '')
QUERY_IDS = [x.strip() for x in QUERY_IDS_RAW.split(",") if x.strip()]

# 交易站 realm：'poe1' 或 'poe2'
REALM = os.getenv('REALM', 'poe1')
# 聯盟名稱，必須與 REALM 成對修改（POE1 例：Covens；POE2 例：Runes of Aldur）
# 只改 REALM 忘了改 LEAGUE 會拿另一款遊戲的聯盟名去打端點，通常回空結果而非報錯
LEAGUE = os.getenv('LEAGUE', 'Covens')
