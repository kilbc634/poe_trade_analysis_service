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
# 取得根目錄路徑
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import POESESSID
from loading_wait import wait_until_stash_visible
from stash_click import click_slot

# === 設定 ===
QUERY_ID = "pJYWvykwu0"   # 你的 live feed query id
# QUERY_ID = "V5Lrp9gwip"
WS_URL = f"wss://www.pathofexile.com/api/trade/live/Keepers/{QUERY_ID}"

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
                fetch_url  = f"https://www.pathofexile.com/api/trade/fetch/{item_token}?query={QUERY_ID}"

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
                whisper_url = "https://www.pathofexile.com/api/trade/whisper"
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
    result = asyncio.run(websocket_main())

    print(result['debug']['item_data'])
    print(result['debug']['whisper_resp'])
    print(result['debug']['after_time'])
    print(result['debug']['fetch_time'])
    print(result['debug']['whisper_time'])

    if 'error' not in result:
        wait_until_stash_visible()
        click_slot(result['x'], result['y'])
        return True
    else:
        return False


if __name__ == "__main__":
    while True:
        status = runner()

        if status == False:
            print("Auto retry after 5s....")
            time.sleep(5)
            continue
        elif status == True:
            print("Done")
            break
