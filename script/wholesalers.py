import time
import sys, os
import traceback
import urllib.parse
import httpx

# 取得根目錄路徑
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import POESESSID, REALM, LEAGUE, QUERY_IDS
from content.common import decode_query_id
from loading_wait import wait_until_stash_visible
from stash_click import click_slot, go_hideout

# === 設定 ===
# 查詢目標固定取 QUERY_IDS 的第一個（本腳本為單線程，只支援單一查詢）
if not QUERY_IDS:
    raise RuntimeError("QUERY_IDS 為空，請於環境變數設定（本腳本只取第一個）")
QUERY_ID = QUERY_IDS[0]
ROUNDS = 40           # 總共輪詢幾輪
POLL_INTERVAL = 2.0   # 每輪一般搜尋的間隔秒數（不求快；注意 trade API 有速率限制）
MAX_FETCH = 10        # 一次 fetch 最多批次幾筆 listing（官方上限就是 10）

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

HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Cookie": f"POESESSID={POESESSID}",
}
HEADERS_XHR = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
}

# === 取得查詢 payload：直接把 QUERY_ID 解碼 ===
def get_payload():
    """把長碼 QUERY_ID 在本地解成查詢 payload；解不出來就印出原因並回 None。

    官方交易網站的查詢 ID 現在是查詢 JSON 本身的 gzip + base64（H4sI 開頭），
    不需要再向任何服務換取。舊的短碼（如 12bdck）已不支援。
    """
    query = decode_query_id(QUERY_ID)
    if not query:
        print("=" * 78)
        print("[ERR] QUERY_ID 解不出查詢內容")
        print(f"      QUERY_ID：{QUERY_ID}")
        print("      ── 這裡只支援官方新版的長碼（H4sI 開頭，交易網址最後那一段）。")
        print("         請確認整段都有貼到、沒有被截斷；舊的短碼已不能用。")
        print("=" * 78)
        return None
    return {"query": query, "sort": {"price": "asc"}}


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


# === 只鎖定最便宜的那一筆 ===
def pick_cheapest(rows, seen):
    """回傳 (row, hideout_token)；最便宜那筆不能買就回 (None, None)，讓上層重新搜尋。

    **不往下找第二便宜的。** payload 的 sort 是 `price: asc`，`rows[0]` 就是這一秒
    全站最低價；往下找等於買貴（極端情況前 10 筆都被買走，第 11 筆可能已從 6c 變 8c）。
    所以第一筆不能買就直接結束本輪、重新 search + fetch，確保每次出手都是當下最低價。

    本腳本的前提是查詢條件設為 **Instant Buyout（`status.option = "securable"`）**，
    這種掛單一定帶 `hideout_token`（可直接傳送過去自助購買，賣家離線也能買），
    所以這裡直接取值不做退路。若查詢沒設成 securable，可能撈到只有 `whisper_token`
    的掛單（例如通貨頁那類，那支 API 只是發密語給賣家、不會傳送），會在這裡 KeyError。
    """
    row = rows[0] if rows else None
    if not row or not row.get("listing"):
        print("[SKIP] 最便宜的那筆已消失 → 重新搜尋")
        return None, None

    listing = row["listing"]
    if row.get("gone"):         # 已被買走/失效（trade 網頁呈 disable 狀態）
        print("[SKIP] 最便宜的那筆已被買走 → 重新搜尋")
        return None, None
    if row.get("id") in seen:   # 這一輪剛處理過，索引還沒更新
        print("[SKIP] 最便宜的那筆已經試過 → 重新搜尋")
        return None, None

    return row, listing["hideout_token"]


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
    print(f"[CFG] REALM={REALM} LEAGUE={LEAGUE} QUERY_ID={QUERY_ID}")
    print(f"[CFG] SEARCH_URL={SEARCH_URL}")

    seen = set()  # 已處理過的 listing id，避免每輪重複密語／重複判斷同一筆

    # 1) 把 QUERY_ID 解成查詢 payload；失敗原因已由 get_payload() 印出
    payload = get_payload()
    if not payload:
        return
    print("[OK] 已解出查詢 payload，開始輪詢一般搜尋...")

    with httpx.Client(timeout=30.0) as client:

        bought = 0
        # 2) 持續輪詢一般搜尋
        for times in range(ROUNDS):
            try:
                query_id, hashes = search(client, payload)
                if not hashes:
                    continue
                rows = fetch(client, query_id, hashes)
                if not rows:
                    continue

                target, token = pick_cheapest(rows, seen)
                if target is None:
                    continue

                listing = target["listing"]
                seen.add(target["id"])
                stash_x = listing["stash"]["x"]
                stash_y = listing["stash"]["y"]
                price = listing.get("price") or {}

                wresp = whisper(client, token)
                print(f"[WHISPER] <{wresp.status_code}> {(wresp.text or '')[:120]} | "
                      f"seller={listing['account']['name']} stash=({stash_x},{stash_y}) "
                      f"price={price.get('amount')} {price.get('currency')} fee={listing.get('fee')}")

                # 角色不在線上就不用再跑了，每一筆都會是同樣的 400
                if wresp.status_code == 400 and "in-game" in (wresp.text or "").lower():
                    print("[ERR] 帳號目前不在遊戲中，無法傳送。請先登入角色再執行。")
                    return

                # 判定傳送是否成功
                success = False
                if wresp.status_code == 200:
                    try:
                        success = wresp.json().get("success") is True
                    except Exception:
                        success = False

                if success:
                    print("[BUY] 傳送成功 → 執行影像辨識購買流程...")
                    if buy_flow(stash_x, stash_y):
                        bought += 1
                        print(f"[BUY] 完成一次購買（累計 {bought} 件，第 {times+1} 輪）")

            except Exception:
                traceback.print_exc()
            finally:
                # 不論這輪是買到、跳過還是出錯，都固定間隔再進下一輪
                time.sleep(POLL_INTERVAL)

        print(f"[DONE] 共 {ROUNDS} 輪，成功購買 {bought} 件")


if __name__ == "__main__":
    main()
