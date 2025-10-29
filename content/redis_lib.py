import sys 
# sys.path.append("..")
from setting import REDIS_HOST, REDIS_AUTH
import redis
from datetime import datetime
import json

RedisClient = redis.Redis(host=REDIS_HOST, port=6379, password=REDIS_AUTH, decode_responses=True)

def set_trade_payload(tradeId, payloadData, poeType, leagueName):
    dbKey = 'poe:trade{poeType}:{leagueName}:{tradeId}'.format(
        poeType=str(poeType),
        leagueName=leagueName.replace(' ', '_'), # 替換空格為底線
        tradeId=tradeId
    )

    RedisClient.set(dbKey, json.dumps(payloadData))

def get_trade_payload(tradeId, poeType=None, leagueName=None):
    if not poeType:
        poeType = '*'
    if not leagueName:
        leagueName = '*'

    pattern = 'poe:trade{poeType}:{leagueName}:{tradeId}'.format(
        poeType=str(poeType),
        leagueName=leagueName.replace(' ', '_'), # 替換空格為底線
        tradeId=tradeId
    )
    keys = list(RedisClient.scan_iter(match=pattern))

    if len(keys) == 0:
        print(f'scan not found any keys ({pattern})')
        return None
    if len(keys) > 1:
        print(f'scan found too many keys ({pattern}) ({keys})')
        return None

    dbKey = keys[0]

    payloadData = RedisClient.get(dbKey)
    if payloadData:
        payloadData = json.loads(payloadData)

    return payloadData
    
