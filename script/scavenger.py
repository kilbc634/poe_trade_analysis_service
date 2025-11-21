import asyncio
import ssl
import certifi
import json
import websockets
# import aiohttp
from datetime import datetime
import requests
import time
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

async def websocket_main():
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    while True:
        print("[WS] Connecting...")

        try:
            async with websockets.connect(
                WS_URL,
                ssl=ssl_context,
                extra_headers=HEADERS,
                ping_interval=None,  # 必須關掉 heartbeat
            ) as ws:
                print("[WS] Connected")

                async for raw_msg in ws:
                    msg = json.loads(raw_msg)

                    # Live feed 可能出現 "result" 或 "new"
                    if "result" in msg:
                        item_token = msg["result"]
                        print(f"[WS] Got item_token = {item_token}")

                        return item_token  # <-- 立即返回，整個 websocket_main 結束
 
        except websockets.exceptions.ConnectionClosed as e:
            print(f"[WS CLOSED] code={e.code} reason={e.reason}")

        except Exception as e:
            print("[WS ERROR]", e)

        print("[WS] Reconnecting in 5s...")
        await asyncio.sleep(5)

def runner():
    item_token = asyncio.run(websocket_main())
    print(f"<NEW RESULT {datetime.now().strftime('%H:%M:%S')}>")

    url = f"https://www.pathofexile.com/api/trade/fetch/{item_token}?query={QUERY_ID}"
    resp = requests.get(url=url, headers=HEADERS)

    item_data = {}
    if resp.status_code == 200:
        data = resp.json()
        print("[FETCH OK]", data)

        item_data['x'] = data['result'][0]['listing']['stash']['x']
        item_data['y'] = data['result'][0]['listing']['stash']['y']
        item_data['hideout_token'] = data['result'][0]['listing']['hideout_token']
    else:
        print("[FETCH ERROR]", resp.status_code, url)

    print(item_data)
    if item_data:
        # 1. 打API跳轉至藏身處
        url = "https://www.pathofexile.com/api/trade/whisper"
        whisper_headers = HEADERS
        whisper_headers['x-requested-with'] = 'XMLHttpRequest'
        resp = requests.post(url=url, headers=whisper_headers, json={
            'token': item_data['hideout_token']
        })
        if resp.status_code == 200:
            data = resp.json()
            # {'success': False} 有可能出現這個
            print("[whisper OK]", data)

            if data['success'] == True:
                # 2. 啟動loading等待腳本，直到loading結束後，接續拉貨腳本
                wait_until_stash_visible()
                click_slot(item_data['x'], item_data['y'])
                return True
        else:
            print("[whisper ERROR]", resp.status_code)

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
