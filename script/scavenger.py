import asyncio
import ssl
import certifi
import json
import websockets
# import aiohttp
import httpx
from datetime import datetime
# import requests
import time
import traceback
import sys, os
import urllib.parse
# 取得根目錄路徑
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import POESESSID, REALM, LEAGUE, QUERY_IDS
from loading_wait import wait_until_stash_visible
from stash_click import click_slot, go_hideout

# === 設定 ===
# 查詢目標固定取 QUERY_IDS 的第一個（本腳本為單線程，只支援單一查詢）
if not QUERY_IDS:
    raise RuntimeError("QUERY_IDS 為空，請於環境變數設定（本腳本只取第一個）")
QUERY_ID = QUERY_IDS[0]

# === Realm 設定（poe1 / poe2），沿用 setting.py ===
# POE1: /api/trade/...            live URL 不含 realm 段、fetch 不帶 realm 參數
# POE2: /api/trade2/... + poe2    live URL 多一段 poe2、fetch 需 &realm=poe2
LEAGUE_ENCODED = urllib.parse.quote(LEAGUE)
if REALM == "poe2":
    API_BASE = "trade2"
    WS_LEAGUE_PATH = f"poe2/{LEAGUE_ENCODED}"
    FETCH_REALM_QS = "&realm=poe2"
else:
    API_BASE = "trade"
    WS_LEAGUE_PATH = LEAGUE_ENCODED
    FETCH_REALM_QS = ""

WS_URL = f"wss://www.pathofexile.com/api/{API_BASE}/live/{WS_LEAGUE_PATH}/{QUERY_ID}"

HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Cookie": f"POESESSID={POESESSID}"
}

HEADERS_WHISPER = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest"
}

async def websocket_main():
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    print("[WS] Connecting...")

    # 單一 httpx client，保持連線池活著
    async with httpx.AsyncClient(http2=True, timeout=2.0) as client:
        async with websockets.connect(
            WS_URL,
            ssl=ssl_context,
            extra_headers=HEADERS,
            ping_interval=None,  # 必須關掉 heartbeat
        ) as ws:
            print("[WS] Connected")

            async for raw_msg in ws:
                # 快速檢查是否含有 result（避免 decode 浪費）
                if "result" not in raw_msg:
                    print(f"[WS] {raw_msg}")
                    continue         

                msg = json.loads(raw_msg)
                item_token = msg["result"]

                # ====== STEP 1: Fetch API（取得商品資料） ======
                fetch_url  = f"https://www.pathofexile.com/api/{API_BASE}/fetch/{item_token}?query={QUERY_ID}{FETCH_REALM_QS}"

                t1 = time.perf_counter()
                fetch_resp = await client.get(
                    fetch_url, 
                    headers=HEADERS,
                    timeout=30.0,
                )
                t1_elapsed = time.perf_counter() - t1

                item_data = fetch_resp.json()
                stash_x = item_data['result'][0]['listing']['stash']['x']
                stash_y = item_data['result'][0]['listing']['stash']['y']
                hideout_token  = item_data['result'][0]['listing']['hideout_token']

                # ====== STEP 2: Whisper API（發動傳送） ======
                whisper_url = f"https://www.pathofexile.com/api/{API_BASE}/whisper"
                payload = {"token": hideout_token}

                t2 = time.perf_counter()
                try:
                    whisper_resp = await client.post(
                        whisper_url,
                        headers=HEADERS_WHISPER,
                        json=payload,
                        timeout=30.0,
                    )
                except:
                    whisper_resp = {
                        'status_code': 'error',
                        'text': 'error'
                    }
                    traceback.print_exc()
                t2_elapsed = time.perf_counter() - t2

                # ====== AFTER: 之後可以不用求速度 ======

                debug = {
                    'item_token': item_token,
                    'item_data': item_data,
                    'hideout_token': hideout_token,
                    'whisper_resp': f"<{whisper_resp.status_code}> {whisper_resp.text or ''}",
                    'after_time': datetime.now().strftime('%H:%M:%S'),
                    'fetch_time': f"fetch {t1_elapsed*1000:.2f} ms",
                    'whisper_time': f"whisper {t2_elapsed*1000:.2f} ms",
                }

                # 沒搶到的話可能會回 404，或者是 {'success': False}
                if whisper_resp.status_code == 200:
                    whisper_data = whisper_resp.json()
                    if whisper_data['success'] == True:
                        return {
                            'x': stash_x,
                            'y': stash_y,
                            'debug': debug,
                        }

                return {
                    'error': 'failed',
                    'debug': debug,
                }

def runner():
    try:
        result = asyncio.run(websocket_main())
    except:
        traceback.print_exc()
        return False

    print(result['debug']['item_data'])
    print(result['debug']['whisper_resp'])
    print(result['debug']['after_time'])
    print(result['debug']['fetch_time'])
    print(result['debug']['whisper_time'])

    if 'error' not in result:
        # 影像辨識等商店 UI；逾時(非 loading 階段 >30s)則強制返回藏身處，進下一輪
        if not wait_until_stash_visible():
            print("等待商店 UI 逾時 → 強制 go_hideout，進入下一輪")
            go_hideout()
            return False
        click_slot(result['x'], result['y'])
        go_hideout()
        return True
    else:
        return False


if __name__ == "__main__":
    for times in range(20):
        status = runner()

        if status == False:
            print(f"Auto retry after 5s.... ({times})")
            time.sleep(5)
            continue
        elif status == True:
            print("Done. buy a item")
            continue
