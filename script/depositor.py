import time
import sys, os
import cv2

# 取得根目錄路徑（讓 from setting import 可用）
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root_dir)
from setting import REALM
from util_config import load_rect_from_ini
from util_image import grab_region, detect_template
from stash_click import ahk, smooth_move_to   # 沿用同一個 AHK 實例與平滑移動

# === 依 REALM 切資源資料夾（poe1 / poe2），路徑錨定本檔位置不受 cwd 影響 ===
RESOURCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resource", REALM)

# === 區域設定 ===
stash_object_rect = load_rect_from_ini(os.path.join(RESOURCE_DIR, "stash_object.ini"))   # 藏身處倉庫物件（點擊）
inventory_rect    = load_rect_from_ini(os.path.join(RESOURCE_DIR, "inventory_grid.ini")) # 背包前 40 格
stash_ui_rect     = load_rect_from_ini(os.path.join(RESOURCE_DIR, "stash_ui.ini"))       # 倉庫 UI 檢查區
inventory_ui_rect = load_rect_from_ini(os.path.join(RESOURCE_DIR, "inventory_ui.ini"))   # 背包 UI 檢查區

# === UI 檢查模板 ===
stash_ui_tmpl     = cv2.imread(os.path.join(RESOURCE_DIR, "stash_ui.png"))
inventory_ui_tmpl = cv2.imread(os.path.join(RESOURCE_DIR, "inventory_ui.png"))

THRESH_UI = 0.95
UI_CHECK_TIMEOUT = 30   # 等倉庫 + 背包 UI 同時出現的逾時秒數

# 背包前 40 格：5 列（高）× 8 行（寬），每格等大
INV_ROWS = 5
INV_COLS = 8
CELL_W = inventory_rect["width"] / INV_COLS
CELL_H = inventory_rect["height"] / INV_ROWS


def _rect_center(rect):
    return int(rect["x"] + rect["width"] / 2), int(rect["y"] + rect["height"] / 2)


def _left_click():
    ahk.send_input("{LButton down}")
    time.sleep(0.05)
    ahk.send_input("{LButton up}")


def open_stash():
    """平滑移動到藏身處倉庫物件中心 → 左鍵點擊 → 等 5 秒讓角色走過去互動。"""
    cx, cy = _rect_center(stash_object_rect)
    smooth_move_to(cx, cy, duration=1.5, steps=30)
    _left_click()
    print(f"[STASH] 點擊倉庫物件 ({cx},{cy})，等待 5 秒走過去互動...")
    time.sleep(5)


def _both_ui_open():
    s = detect_template(grab_region(stash_ui_rect), stash_ui_tmpl, THRESH_UI)
    i = detect_template(grab_region(inventory_ui_rect), inventory_ui_tmpl, THRESH_UI)
    return s and i


def wait_until_both_ui_open(timeout=UI_CHECK_TIMEOUT):
    """輪詢直到「倉庫 UI」與「背包 UI」兩張圖都出現在畫面上；逾時回傳 False。"""
    t_start = time.time()
    while time.time() - t_start < timeout:
        if _both_ui_open():
            print("[STASH] 倉庫 + 背包 UI 已開啟")
            return True
    print(f"[STASH] {timeout}s 內未同時偵測到倉庫/背包 UI")
    return False


def deposit_all():
    """ctrl 全程按住，逐格 ctrl+左鍵把背包前 40 格丟進倉庫。
    由最左 col 起、每 col 由上至下點 5 格，再往右換下一 col（由上至下、由左至右）。
    每格點該格中心，格間平滑移動約 0.5 秒，每點完一格停頓 1 秒；最後放開 ctrl。"""
    ahk.key_down("Ctrl")
    time.sleep(0.1)
    try:
        for col in range(INV_COLS):
            for row in range(INV_ROWS):
                tx = int(inventory_rect["x"] + col * CELL_W + CELL_W / 2)
                ty = int(inventory_rect["y"] + row * CELL_H + CELL_H / 2)
                smooth_move_to(tx, ty, duration=0.5)
                _left_click()
                time.sleep(0.5)
    finally:
        ahk.key_up("Ctrl")
    print("[STASH] 已存入背包前 40 格")


def main():
    print(f"[CFG] REALM={REALM}")
    # 1. 假設角色目前閒置在自己的藏身處
    # 2~3. 點擊藏身處倉庫物件並等待走過去互動
    open_stash()
    # 4. 檢查倉庫 + 背包 UI 是否都已開啟
    if not wait_until_both_ui_open():
        print("[ABORT] 倉庫/背包 UI 未開啟，中止存倉")
        return
    # 5. 把背包前 40 格全部 ctrl+左鍵存入倉庫
    deposit_all()
    print("[DONE] 存倉完成")


if __name__ == "__main__":
    time.sleep(10)
    main()
