import asyncio
import ssl
import certifi
import json
import websockets
import aiohttp
from datetime import datetime
from setting import POESESSID

# === 設定 ===
QUERY_ID = "pJYWvykwu0"   # 你的 live feed query id
# QUERY_ID = "V5Lrp9gwip"
WS_URL = f"wss://www.pathofexile.com/api/trade/live/Keepers/{QUERY_ID}"

HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Cookie": f"POESESSID={POESESSID}"
}

fetch_queue = asyncio.Queue()


async def fetch_worker(session):
    """
    後台 worker，負責 API fetch，不阻塞 WebSocket
    """
    while True:
        item_id = await fetch_queue.get()
        try:
            print(f"<NEW RESULT {datetime.now().strftime('%H:%M:%S')}>")
            url = f"https://www.pathofexile.com/api/trade/fetch/{item_id}?query={QUERY_ID}"

            async with session.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print("[FETCH OK]", data)
                else:
                    print("[FETCH ERROR]", resp.status, item_id)

        except Exception as e:
            print("[FETCH EXCEPTION]", e)

        finally:
            fetch_queue.task_done()


async def websocket_main():
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_context)
    ) as session:

        asyncio.create_task(fetch_worker(session))

        while True:
            print("[WS] Connecting...")

            try:
                async with websockets.connect(
                    WS_URL,
                    ssl=ssl_context,
                    additional_headers=HEADERS,
                    ping_interval=None,  # 必須關掉 heartbeat
                ) as ws:
                    print("[WS] Connected")

                    async for raw_msg in ws:
                        msg = json.loads(raw_msg)

                        # Live feed 可能出現 "result" 或 "new"
                        if "result" in msg:
                            item_id = msg["result"]
                            await fetch_queue.put(item_id)

                        elif "new" in msg:
                            for item_id in msg["new"]:
                                await fetch_queue.put(item_id)

            except websockets.exceptions.ConnectionClosed as e:
                print(f"[WS CLOSED] code={e.code} reason={e.reason}")

            except Exception as e:
                print("[WS ERROR]", e)

            # print("[WS] Reconnecting in 3s...")
            await asyncio.sleep(3)
            break


if __name__ == "__main__":
    asyncio.run(websocket_main())
