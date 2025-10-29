import re
import urllib.parse

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
