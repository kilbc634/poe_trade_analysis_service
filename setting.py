import os

REDIS_HOST = os.getenv('REDIS_HOST', '172.17.0.1')
REDIS_AUTH = os.getenv('REDIS_AUTH', 'cv*****')
BROKER_URL = os.getenv('BROKER_URL', f'redis://:{REDIS_AUTH}@{REDIS_HOST}:6379/0')
SERVICE_HOST = os.getenv('SERVICE_HOST', 'http://tsukumonet.ddns.net:16666/')

POESESSID = os.getenv('POESESSID', '')
QUERY_IDS_RAW = os.getenv('QUERY_IDS', '')
QUERY_IDS = [x.strip() for x in QUERY_IDS_RAW.split(",") if x.strip()]

# 交易站 realm：'poe1' 或 'poe2'
REALM = os.getenv('REALM', 'poe2')
# Live Search 對應的聯盟名稱（POE1 例：Keepers；POE2 例：Runes of Aldur）
LEAGUE = os.getenv('LEAGUE', 'Runes of Aldur')
