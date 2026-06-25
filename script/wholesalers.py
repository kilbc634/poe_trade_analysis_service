import time
import sys, os
import traceback
import urllib.parse
import httpx

# 取得根目錄路徑
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import POESESSID, REALM, LEAGUE, SERVICE_HOST, QUERY_IDS
from loading_wait import wait_until_stash_visible
from stash_click import click_slot, go_hideout

# === 設定 ===
# 查詢目標固定取 QUERY_IDS 的第一個（本腳本為單線程，只支援單一查詢）
if not QUERY_IDS:
    raise RuntimeError("QUERY_IDS 為空，請於環境變數設定（本腳本只取第一個）")
QUERY_ID = QUERY_IDS[0]
POLL_INTERVAL = 2.0   # 每輪一般搜尋的間隔秒數（不求快；注意 trade API 有速率限制）
MAX_FETCH = 10        # 一次 fetch 最多批次幾筆 listing

# === Realm 設定（poe1 / poe2），沿用 setting.py ===
# POE1: /api/trade/...            search/live URL 不含 realm 段、fetch 不帶 realm 參數
# POE2: /api/trade2/... + poe2    search/live URL 多一段 poe2、fetch 需 &realm=poe2
LEAGUE_ENCODED = urllib.parse.quote(LEAGUE)
if REALM == "poe2":
    API_BASE = "trade2"
    LEAGUE_PATH = f"poe2/{LEAGUE_ENCODED}"
    FETCH_REALM_QS = "&realm=poe2"
else:
    API_BASE = "trade"
    LEAGUE_PATH = LEAGUE_ENCODED
    FETCH_REALM_QS = ""

SEARCH_URL  = f"https://www.pathofexile.com/api/{API_BASE}/search/{LEAGUE_PATH}"
WHISPER_URL = f"https://www.pathofexile.com/api/{API_BASE}/whisper"

# 由 QUERY_ID 組出交易頁網址，向雲端 payload 服務(getPayloadByUrlV2)換取查詢 payload
TRADE_URL = f"https://www.pathofexile.com/{API_BASE}/search/{LEAGUE_PATH}/{QUERY_ID}"

HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Cookie": f"POESESSID={POESESSID}",
}
HEADERS_XHR = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
}


# === 取得查詢 payload（來自雲端 payload 服務，內部走 Redis）===
def get_payload(client):
    url = SERVICE_HOST.rstrip("/") + "/trade/getPayloadByUrlV2"
    resp = client.post(url, json={"siteUrl": TRADE_URL}, timeout=30.0)
    resp.raise_for_status()
    return resp.json().get("payloadData")


# === 一般搜尋：POST 完整 payload，回傳 (query_id, [result hashes]) ===
def search(client, payload):
    resp = client.post(SEARCH_URL, headers=HEADERS_XHR, json=payload, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    return data.get("id"), (data.get("result") or [])


# === Fetch：批次取得 listing 詳情，回傳 result 陣列 ===
def fetch(client, query_id, hashes):
    ids = ",".join(hashes[:MAX_FETCH])
    url = f"https://www.pathofexile.com/api/{API_BASE}/fetch/{ids}?query={query_id}{FETCH_REALM_QS}"
    resp = client.get(url, headers=HEADERS, timeout=30.0)
    resp.raise_for_status()
    return resp.json().get("result") or []


# === Whisper：發送 hideout_token 觸發傳送到賣家藏身處 ===
def whisper(client, hideout_token):
    return client.post(WHISPER_URL, headers=HEADERS_XHR, json={"token": hideout_token}, timeout=30.0)


# === 傳送成功後的影像辨識 + 自動購買（與 scavenger.py 相同）===
def buy_flow(stash_x, stash_y):
    # 影像辨識等商店 UI；逾時(非 loading 階段 >30s)則強制返回藏身處，進下一輪
    if not wait_until_stash_visible():
        print("[BUY] 等待商店 UI 逾時 → 強制 go_hideout，進入下一輪")
        go_hideout()
        return False
    click_slot(stash_x, stash_y)
    go_hideout()
    return True


def main():
    print(f"[CFG] REALM={REALM} LEAGUE={LEAGUE}")
    print(f"[CFG] SEARCH_URL={SEARCH_URL}")

    seen = set()  # 已嘗試 whisper 過的 listing id，避免每輪重複密語同一筆

    with httpx.Client(timeout=30.0) as client:
        # 1) 先向雲端 payload 服務取得查詢 payload（只取一次）
        try:
            payload = get_payload(client)
        except Exception:
            traceback.print_exc()
            print("[ERR] 呼叫 payload 服務失敗，請確認 SERVICE_HOST 與雲端服務狀態")
            return
        if not payload:
            print("[ERR] 取不到 payload，請確認 TRADE_URL 是否正確、Redis 是否已有對應資料")
            return
        print("[OK] 已取得查詢 payload，開始輪詢一般搜尋...")

        # 2) 持續輪詢一般搜尋
        for times in range(40):
            try:
                query_id, hashes = search(client, payload)
                rows = fetch(client, query_id, hashes) if hashes else []

                # 找第一筆「還沒嘗試過」且有 listing 的結果
                target = None
                for row in rows:
                    if not row or not row.get("listing"):
                        continue
                    if row.get("gone"):     # 已被買走/失效（trade 網頁呈 disable 狀態），跳過
                        continue
                    if row.get("id") in seen:
                        continue
                    target = row
                    break

                if target is None:
                    time.sleep(POLL_INTERVAL)
                    continue

                listing = target["listing"]
                seen.add(target["id"])
                stash_x = listing["stash"]["x"]
                stash_y = listing["stash"]["y"]
                hideout_token = listing["hideout_token"]

                wresp = whisper(client, hideout_token)
                print(f"[WHISPER] <{wresp.status_code}> {(wresp.text or '')[:120]} | "
                      f"seller={listing['account']['name']} stash=({stash_x},{stash_y})")

                # 判定傳送是否成功
                success = False
                if wresp.status_code == 200:
                    try:
                        success = wresp.json().get("success") is True
                    except Exception:
                        success = False

                if success:
                    print("[BUY] 傳送成功 → 執行影像辨識購買流程...")
                    buy_flow(stash_x, stash_y)
                    print(f"[BUY] 完成一次購買 ({times+1})")

            except Exception:
                traceback.print_exc()

            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
