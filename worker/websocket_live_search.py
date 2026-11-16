import asyncio
import hashlib
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


# === 短代號 ===
# query id 是「查詢 JSON gzip 後的 base64url」，條件越多越長（實測 180~255+ 字元），
# 直接當檔名會超過 Linux 的 255 bytes 上限，放在 console 前綴也難讀。
# 所以檔名與 console 一律用 id 的 sha1 前 8 碼；同一個 id 每次算出來都一樣，重跑會接續寫同一個 log。
def build_tags(query_ids):
    digests = {qid: hashlib.sha1(qid.encode()).hexdigest() for qid in query_ids}
    tags = {qid: d[:8] for qid, d in digests.items()}

    # 8 碼撞號的那幾個改用 12 碼；12 碼還撞就直接失敗，不讓兩個查詢寫進同一個 log
    values = list(tags.values())
    for qid in query_ids:
        if values.count(tags[qid]) > 1:
            tags[qid] = digests[qid][:12]

    if len(set(tags.values())) != len(tags):
        raise RuntimeError(f"query id 的短代號取到 12 碼仍重複：{tags}")
    return tags


TAGS = build_tags(QUERY_IDS)


# === Fetch Worker（每個 Query ID 有自己一個）===
async def fetch_worker(session, query_id):
    tag = TAGS[query_id]
    log_path = f"fetch_{tag}.log"

    print(f"[WORKER {tag}] Start worker, log={log_path}")

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
        # 寫檔失敗只印出來、不讓 worker 結束，否則這個查詢之後的掛單都沒人處理
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(log_line)
                # f.write(log2_line)
        except OSError as e:
            print(f"[WORKER {tag}] LOG WRITE FAILED {log_path}: {e}")

        fetch_queues[query_id].task_done()


# === WebSocket Listener（每個 Query ID 一條）===
async def websocket_listener(query_id, session):
    ws_url = f"wss://www.pathofexile.com/api/{API_BASE}/live/{WS_LEAGUE_PATH}/{query_id}"
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    tag = TAGS[query_id]

    for times in range(3):
        print(f"[WS {tag}] Connecting...")

        try:
            async with connect(
                ws_url,
                ssl=ssl_context,
                additional_headers=HEADERS,
                ping_interval=None,
            ) as ws:
                print(f"[WS {tag}] Connected")

                async for raw_msg in ws:
                    msg = json.loads(raw_msg)

                    if "result" in msg:
                        item_id = msg["result"]
                        await fetch_queues[query_id].put(item_id)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[WS {tag}] CLOSED code={e.code} reason={e.reason}")

        except Exception as e:
            print(f"[WS {tag}] ERROR {e}")

        print(f"[WS {tag}] Reconnecting in 3s... ({times})")
        await asyncio.sleep(5)


# === Main Entry ===
async def main():
    print(f"[MAIN] REALM={REALM} LEAGUE={LEAGUE} API_BASE={API_BASE} 共 {len(QUERY_IDS)} 個查詢")
    # 短代號 ↔ 完整 id 對照，之後的 console 與 log 檔名都只出現短代號
    for qid in QUERY_IDS:
        print(f"[MAIN] {TAGS[qid]} = {qid}")

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
            print(f"[MAIN] Starting listener for {TAGS[qid]} in staggered mode...")
            task = asyncio.create_task(websocket_listener(qid, session))
            listeners.append(task)
            await asyncio.sleep(5)   # 延遲 5 秒再啟動下一個 listener

        # 等所有 listener 同步運行
        await asyncio.gather(*listeners)


if __name__ == "__main__":
    asyncio.run(main())
