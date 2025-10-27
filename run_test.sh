docker run --rm -it \
  -v "$(pwd)":/app \
  -p 5000:5000 \
  tuyn76801/poe_trade_analysis_service:latest \
  python3 app.py
