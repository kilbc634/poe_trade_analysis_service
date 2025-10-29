from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

# 設定 Chrome 選項
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-gpu")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--window-size=1680,1050")


def open_site_to_send_payload_data(url):
    # 啟動 WebDriver
    driver = webdriver.Chrome(options=options)

    # 先打開網站首頁（或任何同域名頁面），讓 Selenium 初始化 domain
    driver.get("https://www.pathofexile.com/")
    time.sleep(2)
    # 注入 cookie，成為登入中狀態
    cookie = {
        "name": "POESESSID",
        "value": "c4cecb5206f3f67ec1ad73f3fc7a2e31",
        "domain": ".pathofexile.com",  # 注意 domain，要包含點
        "path": "/",
        "httpOnly": True,
        "secure": True,
    }
    driver.add_cookie(cookie)

    try:
        with open("worker/interceptor.js", "r", encoding="utf-8") as f:
            js_code = f.read()
        # 然後再導航，腳本會在頁面 JS 執行前就先跑
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": js_code})

        driver.get(url)
        time.sleep(5)

        # 截圖並保存
        driver.save_screenshot("./screenshot.png")
        print("✅ Screenshot saved as screenshot.png")

    finally:
        driver.quit()
