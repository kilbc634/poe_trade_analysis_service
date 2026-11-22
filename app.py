"""【已棄用 DEPRECATED — 2026-11-23】雲端 payload 服務（交易網址 → 查詢 payload）。

官方交易網站把查詢 ID 從伺服器存的短碼改成「長碼」：查詢 JSON 本身的
gzip + base64（H4sI 開頭）。payload 直接從 ID 解得出來
（content/common.py 的 decode_query_id），不需要再靠這台服務去換，
repo 內也已經沒有任何程式呼叫它（script/wholesalers.py 改成本地解碼）。

本檔與它專用的配件保留只為了查舊帳，不再維護，也不必再部署：
  content/redis_lib.py、content/trade_api.py、
  worker/selenium_runner.py、worker/interceptor.js
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
sys.stdout.reconfigure(line_buffering=True)
from worker.selenium_runner import open_site_to_send_payload_data
from content.redis_lib import set_trade_payload, get_trade_payload
from content.common import parse_trade_url
from content.trade_api import fetch_query_payload

print("[DEPRECATED] app.py（雲端 payload 服務）已棄用，查詢 payload 請改用 decode_query_id 本地解碼。")

app = Flask(__name__)
CORS(app)  # ✅ 允許瀏覽器跨來源呼叫

@app.route('/trade/setPayloadMapping', methods=['POST'])
def set_payload_mapping():
    data = request.get_json()

    # 檢查是否有傳入 JSON
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    # 檢查必要參數
    required_fields = ["tradeId", "payloadData", "poeType", "leagueName"]
    missing_fields = [f for f in required_fields if f not in data]

    if missing_fields:
        return jsonify({
            "error": "Missing required parameter(s)",
            "missing": missing_fields
        }), 400

    trade_id = data["tradeId"]
    payload_data = data["payloadData"]
    poe_type = data["poeType"]
    league_name = data["leagueName"]

    set_trade_payload(trade_id, payload_data, poe_type, league_name)

    return jsonify({"status": "OK"}), 200


@app.route('/trade/getPayloadByUrl', methods=['POST'])
def get_payload_by_url():
    data = request.get_json()

    # 檢查是否有傳入 JSON
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    # 檢查必要參數
    required_fields = ["siteUrl"]
    missing_fields = [f for f in required_fields if f not in data]

    if missing_fields:
        return jsonify({
            "error": "Missing required parameter(s)",
            "missing": missing_fields
        }), 400

    site_url = data["siteUrl"]

    urlData = parse_trade_url(site_url)
    if not urlData:
        return jsonify({"error": "URL format error"}), 400

    payloadData = get_trade_payload(
        urlData['tradeId'],
        urlData['poeType'],
        urlData['leagueName']
    )

    if not payloadData:
        open_site_to_send_payload_data(site_url)

        payloadData = get_trade_payload(
            urlData['tradeId'],
            urlData['poeType'],
            urlData['leagueName']
        )

    return jsonify({"payloadData": payloadData}), 200


@app.route('/trade/getPayloadByUrlV2', methods=['POST'])
def get_payload_by_url_v2():
    """與 getPayloadByUrl 相同的輸入/輸出，但 Redis 沒命中時改用官方 GET API
    直接取回查詢 payload（取代 selenium 截包）。"""
    data = request.get_json()

    # 檢查是否有傳入 JSON
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    # 檢查必要參數
    required_fields = ["siteUrl"]
    missing_fields = [f for f in required_fields if f not in data]

    if missing_fields:
        return jsonify({
            "error": "Missing required parameter(s)",
            "missing": missing_fields
        }), 400

    site_url = data["siteUrl"]

    urlData = parse_trade_url(site_url)
    if not urlData:
        return jsonify({"error": "URL format error"}), 400

    payloadData = get_trade_payload(
        urlData['tradeId'],
        urlData['poeType'],
        urlData['leagueName']
    )

    if not payloadData:
        # 用 GET API 直接取回（取代 selenium fallback）
        payloadData = fetch_query_payload(site_url)

        if payloadData:
            set_trade_payload(
                urlData['tradeId'],
                payloadData,
                urlData['poeType'],
                urlData['leagueName']
            )

    return jsonify({"payloadData": payloadData}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
