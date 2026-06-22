# poe_trade_analysis_service

Path of Exile（流亡黯道）官方交易站的**自動監聽 + 自動購買**服務，支援 **POE1 / POE2**（以 `REALM` 切換）。

整體分成兩半：

- **服務端（雲端）**：跑在雲端主機的 Docker 容器，提供「交易網址 → 查詢 payload」的 API，以及（選用的）Live Search 監聽。
- **Local 端（遊戲端）**：跑在開著遊戲的 Windows 機器，監聽到符合條件的掛單後，發出 hideout_token 讓角色傳送到賣家藏身處，再用影像辨識 + AutoHotkey 自動完成購買。

---

## 功能元件

| 檔案 | 角色 | 說明 |
|------|------|------|
| `app.py` | 服務端 | Flask payload 服務（port 5000）。提供下列 endpoint |
| `content/trade_api.py` | 服務端 | `fetch_query_payload()`：用官方 GET API 直接取回查詢 payload（POE2 主力做法） |
| `content/common.py` / `content/redis_lib.py` | 服務端 | 交易網址解析、Redis 存取 |
| `worker/websocket_live_search.py` | 服務端 | Live Search 監聽：依 `QUERY_IDS` 連 WebSocket，收到掛單即 fetch 並寫 log |
| `worker/selenium_runner.py` + `worker/interceptor.js` | 服務端 | 舊版 selenium 截包（`getPayloadByUrl` 的 fallback，POE2 已改用 GET API，保留備援） |
| `script/scavenger.py` | Local | **Live Search 搶快版**：WebSocket → whisper → 影像辨識購買 |
| `script/scavenger_search.py` | Local | **一般搜尋輪詢版**（不搶快）：向服務端取 payload → 輪詢搜尋 → whisper → 影像辨識購買 |
| `script/loading_wait.py` / `stash_click.py` / `util_image.py` / `util_config.py` | Local | 影像辨識（OpenCV）、滑鼠操作（AHK）、區域設定 |
| `script/selector.py` | Local | 校準工具：按 F3 框選螢幕區域，產生 `resource/<realm>/*.ini/.png` |
| `script/resource/poe1/`、`poe2/` | Local | 各 realm 的影像辨識區域座標與模板（`loading_mask`、`normal_UI`、`stash_table`） |

### 服務端 API（`app.py`）

| Endpoint | 用途 |
|----------|------|
| `POST /trade/getPayloadByUrlV2` | **（推薦）** 交易網址 → 查詢 payload；Redis 沒命中時用官方 GET API 取回（POE2 可用、不需登入、不卡 Cloudflare） |
| `POST /trade/getPayloadByUrl` | 舊版：fallback 改用 selenium 開瀏覽器截包（保留備援） |
| `POST /trade/setPayloadMapping` | 由 `interceptor.js` 在瀏覽器截到搜尋 payload 時回傳寫入 Redis |

### 環境變數（`setting.py`）

| 變數 | 預設 | 說明 |
|------|------|------|
| `REALM` | `poe2` | `poe1` 或 `poe2` |
| `LEAGUE` | `Runes of Aldur` | 聯盟名稱（POE1 例：`Keepers`） |
| `POESESSID` | （空） | 登入 session cookie。Live Search / 搶快購買需要；`getPayloadByUrlV2` 不需要 |
| `QUERY_IDS` | （空） | 逗號分隔的已存搜尋 id（Live Search 用） |
| `SERVICE_HOST` | `http://tsukumonet.ddns.net:16666/` | Local 端呼叫服務端的位址 |
| `REDIS_HOST` | `172.17.0.1` | Redis 位址（容器內連主機用 docker bridge gateway） |
| `REDIS_AUTH` | `cv*****`（**需覆蓋為真實密碼**） | Redis 密碼 |

---

## 快速開始 — 服務端（雲端主機）

前置：已安裝 Docker、Redis 常駐（僅內網）、已 build/pull `tuyn76801/poe_trade_analysis_service:latest`。

```bash
cd ~/poe_trade_analysis_service
git pull

# 1) Payload 服務（getPayloadByUrlV2）— 提供給 local 端的一般搜尋取 payload
docker run -d --name poe_payload --restart unless-stopped \
  -v "$(pwd)":/app -w /app \
  -p 5000:5000 \
  -e REDIS_HOST=172.17.0.1 -e REDIS_AUTH=<你的redis密碼> \
  tuyn76801/poe_trade_analysis_service:latest python3 app.py
# 註：容器內聽 5000；對外請依你的 SERVICE_HOST 設定對應 port（例：-p 16666:5000）
```

```bash
# 2)（選用）Live Search 監聽 — 給搶快版 scavenger.py 用
docker run -d --name poe_live --restart unless-stopped \
  -v "$(pwd)":/app -w /app \
  -e POESESSID=<你的POESESSID> \
  -e QUERY_IDS=<id1,id2,...> \
  -e REALM=poe2 -e LEAGUE="Runes of Aldur" \
  tuyn76801/poe_trade_analysis_service:latest python3 worker/websocket_live_search.py
```

驗證 payload 服務：

```bash
curl -s -X POST localhost:5000/trade/getPayloadByUrlV2 \
  -H 'Content-Type: application/json' \
  -d '{"siteUrl":"https://www.pathofexile.com/trade2/search/poe2/Runes%20of%20Aldur/<query_id>"}'
```

---

## 快速開始 — Local 端腳本（遊戲端 Windows）

前置：

```bash
# Python 套件
pip install websockets "httpx[http2]" certifi requests opencv-python mss numpy pillow ahk
```

- 另需安裝 **AutoHotkey 本體**（`script/selector.py` 預設路徑 `C:\Program Files\AutoHotkey\AutoHotkey.exe`）。
- **影像辨識區域需先校準**（每台機器 / 每種解析度做一次）：
  ```bash
  cd script
  python selector.py        # 按 F3 框選 → 產生 sampling-* 資料夾
  # 將框到的 loading_mask / normal_UI / stash_table 對應檔放入 resource/<realm>/
  ```

設定環境變數（PowerShell 例）：

```powershell
$env:REALM   = "poe2"
$env:LEAGUE  = "Runes of Aldur"
$env:POESESSID = "<你的POESESSID>"
$env:SERVICE_HOST = "http://<雲端位址>:16666/"   # 一般搜尋版需要
```

### A. 一般搜尋輪詢版（不搶快）— `scavenger_search.py`

1. 編輯 `script/scavenger_search.py` 最上方的 `TRADE_URL`，填入你的 POE2 查詢頁網址（含 query_id）。
2. 執行：
   ```bash
   cd script
   python scavenger_search.py
   ```
   流程：向服務端 `getPayloadByUrlV2` 取 payload → 輪詢一般搜尋 → 找到掛單 → whisper 傳送 → 影像辨識購買 → 回藏身處。

### B. Live Search 搶快版 — `scavenger.py`

1. 編輯 `script/scavenger.py` 最上方的 `QUERY_ID`，填入要監聽的已存搜尋 id。
2. 執行：
   ```bash
   cd script
   python scavenger.py
   ```
   流程：WebSocket 監聽 → 收到掛單即 fetch + whisper（搶速度）→ 影像辨識購買。

> ⚠️ 兩支 local 腳本都會**實際操作你的遊戲角色**（傳送、移動滑鼠、Ctrl+點擊購買），請在可控環境下測試。
