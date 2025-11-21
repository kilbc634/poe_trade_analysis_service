import cv2
import time
from util_config import load_rect_from_ini
from util_image import grab_region, detect_template

# === 載入特徵 ===
loading_rect = load_rect_from_ini("resource/loading_mask.ini")
ui_rect      = load_rect_from_ini("resource/normal_UI.ini")

loading_tmpl = cv2.imread("resource/loading_mask.png")
ui_tmpl      = cv2.imread("resource/normal_UI.png")

# 閾值可微調
THRESH_LOADING = 0.95
THRESH_UI = 0.95

# === 狀態 ===
STATE_IDLE = 0
STATE_LOADING = 1
STATE_WAIT_UI = 2

# loading_start_time = None

# freq_count = 0

def wait_until_stash_visible():
    state = STATE_IDLE
    while True:

        if state == STATE_IDLE:
            region = grab_region(loading_rect)
            if detect_template(region, loading_tmpl, THRESH_LOADING):
                print("偵測到 loading_mask！...")
                # loading_start_time = time.time()
                state = STATE_LOADING
            continue

        elif state == STATE_LOADING:
            # freq_count = freq_count + 1
            # 高頻掃描
            # 建議不要硬 sleep，讓 CPU 滿跑最快
            region = grab_region(loading_rect)
            if not detect_template(region, loading_tmpl, THRESH_LOADING):
                print("loading_mask 消失 → Loading 畫面結束")
                state = STATE_WAIT_UI
                # print(f"freq_count = {str(freq_count)}")
                # freq_count = 0
            continue

        elif state == STATE_WAIT_UI:
            # 高頻掃描 normal UI
            region = grab_region(ui_rect)
            if detect_template(region, ui_tmpl, THRESH_UI):
                # elapsed = time.time() - loading_start_time
                print(f"正常 UI 出現！")
                break
            continue
