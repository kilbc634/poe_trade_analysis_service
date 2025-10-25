#!/bin/bash

# 啟動 app.py 並在背景執行
echo "[INFO] 啟動 Flask 主程式 app.py ..."
nohup python3 app.py > app.log 2>&1 &

# 等待 10 秒
echo "[INFO] 等待 10 秒讓 Flask 啟動中..."
sleep 10

# 執行 selenium_runner.py
echo "[INFO] 啟動 Selenium Runner ..."
python3 worker/selenium_runner.py
sleep 3
