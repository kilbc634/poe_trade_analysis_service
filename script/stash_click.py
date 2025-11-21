import configparser
import time
import random
from ahk import AHK

ahk = AHK()

# -----------------------------------------------------
# 設定讀取
# -----------------------------------------------------
def load_rectangle_settings(ini_path="resource/stash_table.ini"):
    config = configparser.ConfigParser()
    config.read(ini_path)

    rect = config["Rectangle"]
    x = int(rect["x"])
    y = int(rect["y"])
    width = int(rect["width"])
    height = int(rect["height"])

    return x, y, width, height


RECT_X, RECT_Y, RECT_W, RECT_H = load_rectangle_settings()
ROWS = 12
COLS = 12

CELL_W = RECT_W / COLS
CELL_H = RECT_H / ROWS


# -----------------------------------------------------
# 平滑移動（先快後慢）
# duration：總耗時秒數（預設 0.5）
# -----------------------------------------------------
def smooth_move_to(x2, y2, duration=0.1, steps=10):
    x1, y1 = ahk.mouse_position

    for i in range(steps + 1):
        t = i / steps  # 0 ~ 1

        # ease-out（先快後慢）
        ease_t = 1 - (1 - t) * (1 - t)

        nx = int(x1 + (x2 - x1) * ease_t)
        ny = int(y1 + (y2 - y1) * ease_t)

        ahk.mouse_move(nx, ny, speed=0)  # 使用 speed=0 讓位置可控
        time.sleep(duration / steps)


# -----------------------------------------------------
# 主函式：真人化 ctrl + left click
# -----------------------------------------------------
def click_slot(col: int, row: int):
    if not (0 <= row < ROWS and 0 <= col < COLS):
        raise ValueError("row / col must be 0~11")

    # 算出該格中心
    tx = int(RECT_X + col * CELL_W + CELL_W / 2)
    ty = int(RECT_Y + row * CELL_H + CELL_H / 2)
    # print(f"ROW = {row}, COL = {col}")
    # print(f"RECT_X = {RECT_X}, RECT_Y = {RECT_Y}, CELL_W = {CELL_W}, CELL_H = {CELL_H}, target = ({tx}, {ty})")

    # -------------------------------------------------
    # 1. 預先瞬移到目標附近四點之一（±80px）
    # -------------------------------------------------
    offset = 60
    candidates = [
        (tx + offset, ty),     # 右
        (tx - offset, ty),     # 左
        (tx, ty + offset),     # 下
        (tx, ty - offset),     # 上
    ]
    px, py = random.choice(candidates)

    ahk.mouse_move(px, py, speed=0)   # 瞬移
    # time.sleep(0.05)

    # -------------------------------------------------
    # 2. 用先快後慢的方式平滑移動到目標
    # -------------------------------------------------
    smooth_move_to(tx, ty)

    # -------------------------------------------------
    # 3. 模擬真人：先按住 ctrl → 0.2秒 → 左鍵按住 0.2秒 → 放開
    # -------------------------------------------------
    ahk.key_down("Ctrl")
    time.sleep(0.1)

    ahk.send_input("{LButton down}")  # 按下左鍵
    time.sleep(0.1)
    ahk.send_input("{LButton up}")    # 放開左鍵

    ahk.key_up("Ctrl")
    time.sleep(0.1)


# 測試用：
# click_slot(4, 7)
