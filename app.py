from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
sys.stdout.reconfigure(line_buffering=True)
import re
from worker.selenium_runner import open_site_to_get_payload_data
from redis_context.redis_lib import set_trade_payload, get_trade_payload

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
    open_site_to_get_payload_data(site_url)

    lastPath = re.search(r"/([^/?#]+)(?:[?#]|$)", site_url).group(1)
    payloadData = get_trade_payload(lastPath)

    return jsonify({"payloadData": payloadData}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
