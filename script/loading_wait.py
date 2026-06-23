import cv2
import time
import sys, os
# 取得根目錄路徑（讓 from setting import 可用）
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import REALM
from util_config import load_rect_from_ini
from util_image import grab_region, detect_template

# === 依 REALM 切資源資料夾（poe1 / poe2），路徑錨定本檔位置不受 cwd 影響 ===
RESOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource", REALM)

# === 載入特徵 ===
loading_rect = load_rect_from_ini(os.path.join(RESOURCE_DIR, "loading_mask.ini"))
ui_rect      = load_rect_from_ini(os.path.join(RESOURCE_DIR, "normal_UI.ini"))

loading_tmpl = cv2.imread(os.path.join(RESOURCE_DIR, "loading_mask.png"))
ui_tmpl      = cv2.imread(os.path.join(RESOURCE_DIR, "normal_UI.png"))

# 閾值可微調
THRESH_LOADING = 0.95
THRESH_UI = 0.95

# 非 loading 階段（等 loading 開始 / 等 normal UI）的逾時秒數；loading 畫面本身不限制
NON_LOADING_TIMEOUT = 30

# === 狀態 ===
STATE_IDLE = 0
STATE_LOADING = 1
STATE_WAIT_UI = 2


def _loading_present():
    return detect_template(grab_region(loading_rect), loading_tmpl, THRESH_LOADING)


def wait_until_stash_visible(non_loading_timeout=NON_LOADING_TIMEOUT):
    """等待傳送後商店 normal UI 出現。
    loading 畫面本身不限時；但「等 loading 開始」與「等 normal UI」兩個非 loading 階段
    各限制 non_loading_timeout 秒，逾時回傳 False（讓呼叫端強制 go_hideout 進下一輪）。
    成功回傳 True。"""
    state = STATE_IDLE
    t_start = time.time()
    while True:

        if state == STATE_IDLE:
            if time.time() - t_start > non_loading_timeout:
                print(f"[TIMEOUT] {non_loading_timeout}s 內未偵測到 loading 開始")
                return False
            if _loading_present():
                print("偵測到 loading_mask！...")
                state = STATE_LOADING
            continue

        elif state == STATE_LOADING:
            # loading 畫面中（高頻掃描，不限時）
            if not _loading_present():
                print("loading_mask 消失 → Loading 畫面結束")
                state = STATE_WAIT_UI
                t_start = time.time()   # 重置計時，給 WAIT_UI 階段
            continue

        elif state == STATE_WAIT_UI:
            if time.time() - t_start > non_loading_timeout:
                print(f"[TIMEOUT] {non_loading_timeout}s 內未偵測到 normal UI")
                return False
            if detect_template(grab_region(ui_rect), ui_tmpl, THRESH_UI):
                print("正常 UI 出現！")
                time.sleep(0.5)
                return True
            continue


def wait_until_loading_done(appear_timeout=10, settle=3):
    """用於返回藏身處：偵測 loading 畫面，loading_mask 消失後再等 settle 秒。
    若 appear_timeout 秒內都沒偵測到 loading（可能瞬間完成或已在藏身處），直接 settle。"""
    t_start = time.time()
    # 1) 等 loading 出現
    while not _loading_present():
        if time.time() - t_start > appear_timeout:
            print("[go_hideout] 未偵測到 loading，直接 settle")
            time.sleep(settle)
            return
    # 2) 等 loading 消失（loading 畫面本身不限時）
    while _loading_present():
        pass
    print("loading_mask 消失 → 已返回藏身處")
    time.sleep(settle)
