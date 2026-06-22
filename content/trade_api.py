import urllib.parse
import requests
from setting import POESESSID
from content.common import parse_trade_url

_HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}


def _build_saved_search_url(url_data):
    """依 realm 組出「取回已存搜尋定義」的 GET API 網址。
    POE1: /api/trade/search/{league}/{id}
    POE2: /api/trade2/search/poe2/{league}/{id}?realm=poe2
    """
    league_enc = urllib.parse.quote(url_data["leagueName"])
    trade_id = url_data["tradeId"]
    if url_data["poeType"] == 2:
        return f"https://www.pathofexile.com/api/trade2/search/poe2/{league_enc}/{trade_id}?realm=poe2"
    return f"https://www.pathofexile.com/api/trade/search/{league_enc}/{trade_id}"


def fetch_query_payload(site_url):
    """用官方 GET API 直接取回該 trade 網址(含 query_id)對應的搜尋 payload，
    取代 selenium 截包的作法。

    GET 回傳只含 query(且會省略 null / disabled:false 等無意義預設值，
    但這些省略不影響查詢結果)，這裡補上預設 sort(買最便宜)後，
    整包即可直接 POST 給搜尋 API。

    成功回傳可直接 POST 的 {"query": ..., "sort": ...}，失敗回 None。
    """
    url_data = parse_trade_url(site_url)
    if not url_data:
        print(f"[trade_api] URL 格式錯誤: {site_url}")
        return None

    api_url = _build_saved_search_url(url_data)
    headers = {**_HEADERS, "Cookie": f"POESESSID={POESESSID}"}

    try:
        resp = requests.get(api_url, headers=headers, timeout=30)
    except Exception as e:
        print(f"[trade_api] GET 例外 {api_url} {e}")
        return None

    if resp.status_code != 200:
        print(f"[trade_api] GET 非 200: {resp.status_code} {api_url}")
        return None

    try:
        query = resp.json().get("query")
    except Exception as e:
        print(f"[trade_api] JSON 解析失敗 {e}")
        return None

    if not query:
        print(f"[trade_api] 回應無 query 欄位: {api_url}")
        return None

    return {"query": query, "sort": {"price": "asc"}}
