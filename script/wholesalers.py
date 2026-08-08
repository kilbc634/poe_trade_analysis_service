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

# 由 QUERY_ID 組出交易頁網址，向雲端 payload 服務(getPayloadByUrlV2)換取查詢 payload
TRADE_URL = f"https://www.pathofexile.com/{API_BASE}/search/{LEAGUE_PATH}/{QUERY_ID}"

HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Cookie": f"POESESSID={POESESSID}",
}
HEADERS_XHR = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
}

# === 錯誤訊息：把「自架服務掛了」跟「官方 API 有問題」明確區分開 ===
def _print_service_error(url, what, cause):
    print("=" * 78)
    print(f"[ERR] 取不到查詢 payload：{what}")
    print(f"      服務位址：{url}")
    print(f"      可能原因：{cause}")
    print("      ── 這是 SERVICE_HOST 指到的『自架 payload 服務』(app.py) 的問題，")
    print("         不是官方交易 API 擋你，也不是這支腳本的邏輯有錯。")
    print("      ── 先確認那台服務（Docker container）還活著、對外 port 有開。")
    print("=" * 78)


# === 取得查詢 payload（來自雲端 payload 服務，內部走 Redis）===
def get_payload(client):
    """向雲端 payload 服務取查詢 payload；失敗時印出可直接對症的訊息並回 None。"""
    url = SERVICE_HOST.rstrip("/") + "/trade/getPayloadByUrlV2"

    try:
        resp = client.post(url, json={"siteUrl": TRADE_URL}, timeout=30.0)
    except httpx.TimeoutException:
        _print_service_error(url, "連線逾時（30 秒內沒有任何回應）",
                             "服務卡住、或防火牆把封包丟掉了")
        return None
    except httpx.RequestError as e:
        _print_service_error(url, f"連不上（{type(e).__name__}: {e}）",
                             "服務沒有啟動、port 沒開、或 SERVICE_HOST 設錯了")
        return None

    if resp.status_code != 200:
        _print_service_error(url, f"服務回了 HTTP {resp.status_code}",
                             "服務活著但處理失敗，請看服務端 log")
        print(f"      回應內容：{(resp.text or '')[:200]}")
        return None

    try:
        payload = resp.json().get("payloadData")
    except Exception:
        _print_service_error(url, "回應不是合法的 JSON",
                             "SERVICE_HOST 可能指到了別的服務")
        print(f"      回應內容：{(resp.text or '')[:200]}")
        return None

    if not payload:
        # 這種情況服務是活的，問題在查詢本身，訊息要往另一個方向指
        print("=" * 78)
        print("[ERR] payload 服務有正常回應，但查不到這個查詢的 payload（payloadData 是空的）")
        print(f"      服務位址：{url}")
        print(f"      查詢網址：{TRADE_URL}")
        print("      ── 服務本身沒問題。請檢查 QUERY_IDS / LEAGUE / REALM 是否設對，")
        print("         以及該查詢是否真的存在（用瀏覽器打開上面那個網址看看）。")
        print("=" * 78)
        return None

    return payload


# === 備援：雲端服務掛掉時，直接跟官方 GET 已存搜尋 API 要 query 定義 ===
# 2026-08-09 使用者決定先不啟用，維持 getPayloadByUrlV2 為唯一來源；日後視情況再導入。
# 啟用方式：解除註解，並在 get_payload() 失敗的分支改成 return get_payload_from_official(client)
# def get_payload_from_official(client):
#     """GET /api/trade/search/{league}/{id} 會回 {"id", "query"}（省略 null 等預設值，不影響查詢），
#     補上 sort 後即可直接 POST 給搜尋 API。與服務端 content/trade_api.py 同一支端點。"""
#     url = f"{SEARCH_URL}/{QUERY_ID}" + ("?realm=poe2" if REALM == "poe2" else "")
#     resp = client.get(url, headers=HEADERS_XHR, timeout=30.0)
#     resp.raise_for_status()
#     query = resp.json().get("query")
#     return {"query": query, "sort": {"price": "asc"}} if query else None


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

    with httpx.Client(timeout=30.0) as client:
        # 1) 先向雲端 payload 服務取得查詢 payload（只取一次）
        #    失敗原因已由 get_payload() 分類印出，這裡直接結束就好
        payload = get_payload(client)
        if not payload:
            return
        print("[OK] 已取得查詢 payload，開始輪詢一般搜尋...")

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
