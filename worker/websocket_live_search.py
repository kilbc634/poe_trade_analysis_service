import asyncio
import ssl
import certifi
import json
import websockets
from websockets.asyncio.client import connect
import aiohttp
from datetime import datetime
import time
import sys, os
import urllib.parse

# === 自訂 Setting ===
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import POESESSID, QUERY_IDS, REALM, LEAGUE

# === Realm 設定（poe1 / poe2）===
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

# 你要同時監聽的 Query IDs
# QUERY_IDS = [
#     "pJYWvykwu0", # 獵首
#     "bG8VpbjzUL", # 魔血
#     "D6VdnK45u5", # 滅日
#     "OgKWdyWlTE", # 未鑑定崇高願景
#     "5n45nqXmfa", # 史瓦林
#     "QL3G8jdvCw", # 尼米斯
#     "yYpDowKlhR", # 卡蘭德之觸
#     "2Kn2ewJeIk", # 命運卡水
#     "9zdLOy9YCK", # 生育
# ]

HEADERS = {
    "Origin": "https://www.pathofexile.com",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Cookie": f"POESESSID={POESESSID}"
}

HEADERS_WHISPER = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest"
}

# 每個 query_id 需要自己的 queue（實際 Queue 在 main() 內、running loop 中建立）
fetch_queues = {}


# === Fetch Worker（每個 Query ID 有自己一個）===
async def fetch_worker(session, query_id):
    log_path = f"fetch_{query_id}.log"

    print(f"[WORKER] Start worker for {query_id}, log={log_path}")

    while True:
        item_id = await fetch_queues[query_id].get()

        url = f"https://www.pathofexile.com/api/{API_BASE}/fetch/{item_id}?query={query_id}{FETCH_REALM_QS}"
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        t1 = time.perf_counter()
        try:
            async with session.get(url, headers=HEADERS) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    log_line = f"[{timestamp}] FETCH OK => {json.dumps(data, ensure_ascii=False)}\n"
                    log_line += f" >>> {data['result'][0]['item']['name']} {data['result'][0]['item']['baseType']} - {data['result'][0]['listing']['price']['amount']} {data['result'][0]['listing']['price']['currency']}\n"
                else:
                    log_line = f"[{timestamp}] FETCH ERROR {resp.status} {item_id}\n"

        except Exception as e:
            log_line = f"[{timestamp}] FETCH EXCEPTION {item_id} {e}\n"
        t1_elapsed = time.perf_counter() - t1
        log_line += f"( fetch {t1_elapsed*1000:.2f} ms )\n"


        # whisper_url = f"https://www.pathofexile.com/api/{API_BASE}/whisper"
        # # 依賣家掛單方式，listing 只會有 hideout_token 或 whisper_token 其中一個（POE1/POE2 皆同）
        # listing = data['result'][0]['listing']
        # token = listing.get('hideout_token') or listing.get('whisper_token')
        # payload = {"token": token}
        # t2 = time.perf_counter()
        # try:
        #     async with session.post(whisper_url, headers=HEADERS_WHISPER, json=payload) as resp:
        #         if resp.status == 200:
        #             resp_data = await resp.json()
        #             log2_line = f"[{timestamp}] Whisper OK => {json.dumps(resp_data, ensure_ascii=False)}\n"
        #         else:
        #             log2_line = f"[{timestamp}] Whisper ERROR {resp.status} {item_id}\n"
        # except Exception as e:
        #     log2_line = f"[{timestamp}] Whisper EXCEPTION {item_id} {e}\n"
        # t2_elapsed = time.perf_counter() - t2
        # log2_line += f"( Whisper {t2_elapsed*1000:.2f} ms )\n"

        # 追加寫入 log
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_line)
            # f.write(log2_line)

        fetch_queues[query_id].task_done()


# === WebSocket Listener（每個 Query ID 一條）===
async def websocket_listener(query_id, session):
    ws_url = f"wss://www.pathofexile.com/api/{API_BASE}/live/{WS_LEAGUE_PATH}/{query_id}"
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    for times in range(3):
        print(f"[WS {query_id}] Connecting...")

        try:
            async with connect(
                ws_url,
                ssl=ssl_context,
                additional_headers=HEADERS,
                ping_interval=None,
            ) as ws:
                print(f"[WS {query_id}] Connected")

                async for raw_msg in ws:
                    msg = json.loads(raw_msg)

                    if "result" in msg:
                        item_id = msg["result"]
                        await fetch_queues[query_id].put(item_id)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[WS {query_id}] CLOSED code={e.code} reason={e.reason}")

        except Exception as e:
            print(f"[WS {query_id}] ERROR {e}")

        print(f"[WS {query_id}] Reconnecting in 3s... ({times})")
        await asyncio.sleep(5)


# === Main Entry ===
async def main():
    print(f"[MAIN] REALM={REALM} LEAGUE={LEAGUE} API_BASE={API_BASE} QUERY_IDS={QUERY_IDS}")

    # 在 running loop 中建立每個 query_id 的 queue
    for qid in QUERY_IDS:
        fetch_queues[qid] = asyncio.Queue()

    ssl_context = ssl.create_default_context(cafile=certifi.where())

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(ssl=ssl_context)
    ) as session:

        # 啟動所有 fetch workers
        for qid in QUERY_IDS:
            asyncio.create_task(fetch_worker(session, qid))

        await asyncio.sleep(1)

        listeners = []

        # 逐個啟動 WebSocket 監聽，每個間隔 5 秒
        for qid in QUERY_IDS:
            print(f"[MAIN] Starting listener for {qid} in staggered mode...")
            task = asyncio.create_task(websocket_listener(qid, session))
            listeners.append(task)
            await asyncio.sleep(5)   # 延遲 5 秒再啟動下一個 listener

        # 等所有 listener 同步運行
        await asyncio.gather(*listeners)


if __name__ == "__main__":
    asyncio.run(main())
