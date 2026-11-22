import base64
import gzip
import json
import re
import urllib.parse


def decode_query_id(trade_id):
    """把新版「長碼」查詢 ID 解回查詢本體（dict）；不是長碼就回 None。

    官方交易網站現在的網址不再是伺服器存的短碼（如 12bdck），而是查詢 JSON 本身
    經 gzip + urlsafe base64（去掉 padding）後的字串，固定以 gzip 檔頭 `H4sI` 開頭。
    舊的 GET /api/trade/search/{league}/{id} 對長碼回 404，所以只能在本地解。
    解出來的就是 payload 的 "query" 那一層，補上 sort 即可 POST 給搜尋 API。
    """
    if not trade_id or not trade_id.startswith("H4sI"):
        return None
    try:
        raw = base64.urlsafe_b64decode(trade_id + "=" * (-len(trade_id) % 4))
        query = json.loads(gzip.decompress(raw))
    except Exception:
        return None
    return query if isinstance(query, dict) else None

def parse_trade_url(url):
    """
    解析 Path of Exile 官方交易網址，回傳 {poeType, tradeId, leagueName}
    
    網址範例：
    - POE1: https://www.pathofexile.com/trade/search/Standard/12bdck
    - POE2: https://www.pathofexile.com/trade2/search/poe2/Rise%20of%20the%20Abyssal/lrl57PViV
    """
    
    poeType = None
    tradeId = None
    leagueName = None

    # 用正則判斷網址開頭 (允許有或沒有 www.)
    if re.match(r'^https:\/\/(www\.)?pathofexile\.com\/trade\/', url):
        poeType = 1
    elif re.match(r'^https:\/\/(www\.)?pathofexile\.com\/trade2\/', url):
        poeType = 2

    # 使用正則擷取最後兩段 path
    # 例如 /search/poe2/Rise%20of%20the%20Abyssal/lrl57PViV
    match = re.search(r'/([^/]+)/([^/]+)$', url)
    if match:
        leagueName_encoded = match.group(1)
        tradeId = match.group(2)
        # 將 %20 轉換成空白
        leagueName = urllib.parse.unquote(leagueName_encoded)

    # 確認都取得成功
    if poeType and tradeId and leagueName:
        return {
            "poeType": poeType,
            "tradeId": tradeId,
            "leagueName": leagueName
        }
    else:
        return None
