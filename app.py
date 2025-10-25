from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
sys.stdout.reconfigure(line_buffering=True)

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

    print(f"trade_id: {trade_id}")
    print(f"payload_data: {payload_data}")
    print(f"poe_type: {poe_type}")
    print(f"league_name: {league_name}")

    return jsonify({"status": "OK"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
