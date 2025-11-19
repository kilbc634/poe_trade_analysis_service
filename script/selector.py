from ahk import AHK
import subprocess
import os
import threading
import configparser
from PIL import ImageGrab
import shutil
from datetime import datetime


# 初始化 AHK（手動指定 AutoHotkey.exe 路徑）
ahk_exe = 'C:\\Program Files\\AutoHotkey\\AutoHotkey.exe'
Ahk = AHK(executable_path=ahk_exe)

ahk_proc = None
f3_hotkey = False


def enable_python_f3():
    global f3_hotkey
    if f3_hotkey is False:
        Ahk.add_hotkey('F3', callback=on_f3_pressed)
        f3_hotkey = True
        print("[Python] 已啟用 F3 熱鍵監聽")

def disable_python_f3():
    global f3_hotkey
    if f3_hotkey is True:
        Ahk.remove_hotkey('F3')
        f3_hotkey = False
        print("[Python] 已停用 F3 熱鍵監聽（交給 AHK）")

def on_f3_pressed():
    global ahk_proc

    print("[Python] F3 按下 → 啟動 AHK 並停用 Python F3")
    disable_python_f3()

    ahk_proc = subprocess.Popen(
        [ahk_exe, "selector.ahk"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    # 建立 thread 監聽 AHK 是否結束
    watcher = threading.Thread(target=after_ahk_exit, daemon=True)
    watcher.start()

def after_ahk_exit():
    global ahk_proc

    ahk_proc.wait()  # 阻塞直到 AHK 完全退出
    print("[Python] 偵測到 AHK 腳本已退出")

    ahk_proc = None

    # AHK 結束 → Python 再次取回 F3 控制權
    enable_python_f3()

    ini_path = "selector.ini"
    if not os.path.exists(ini_path):
        print("[Python] selector.ini 不存在，無法截圖")
        return

    # --- 建立輸出資料夾 ---
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_folder = f"sampling-{timestamp}"
    os.makedirs(output_folder, exist_ok=True)

    # --- 讀取 selector.ini ---
    config = configparser.ConfigParser()
    config.read(ini_path, encoding="utf-8")

    try:
        x = int(config["Rectangle"]["x"])
        y = int(config["Rectangle"]["y"])
        w = int(config["Rectangle"]["width"])
        h = int(config["Rectangle"]["height"])
    except Exception as e:
        print("[Python] 讀取 selector.ini 失敗：", e)
        return

    left = x
    top = y
    right = x + w
    bottom = y + h

    print(f"[Python] 截圖區域: {left}, {top}, {right}, {bottom}")

    # --- 截圖並保存 ---
    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        screenshot_path = os.path.join(output_folder, "sampling.png")
        img.save(screenshot_path)
        print(f"[Python] 已完成截圖 → {screenshot_path}")
    except Exception as e:
        print("[Python] 截圖失敗：", e)
        return

    # --- 複製 ini 並重新命名 ---
    try:
        ini_copy_path = os.path.join(output_folder, "sampling.ini")
        shutil.copyfile(ini_path, ini_copy_path)
        print(f"[Python] 已複製 selector.ini → {ini_copy_path}")
    except Exception as e:
        print("[Python] 無法複製 ini 檔案：", e)


if __name__ == "__main__":
    # 啟動時 Python 先接管 F3
    enable_python_f3()

    Ahk.start_hotkeys()
    print("[*] 熱鍵 F3 已綁定，等待觸發...")
    Ahk.block_forever()
