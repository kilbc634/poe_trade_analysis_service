# -*- coding: utf-8 -*-
"""
物品資訊記錄器

功能：
- 按下快捷鍵 "v" 會自動觸發 ctrl+c（POE 中會複製滑鼠當前位置物品的資訊到剪貼簿）
- 從剪貼簿取得物品資訊，擷取最上面的第一個區塊
- 將擷取結果寫入同目錄底下的記錄檔（不存在則新建）
- 每一筆紀錄都有流水號，從 1 開始，每進一筆 +1（編號即代表目前資料筆數）

流程細節：
- ctrl+c 之前先清空剪貼簿，避免誤用之前的值
- ctrl+c 之後檢查剪貼簿是否有內容，沒有則重試 ctrl+c，最多 3 次，最終仍空白則放棄寫入

需求套件：
    pip install keyboard pyperclip
"""

import ctypes
import ctypes.wintypes as wintypes
import itertools
import os
import threading
import time

import keyboard
import pyperclip

# ---- 設定 ----
HOTKEY = "v"                              # 觸發快捷鍵
SEPARATOR = "--------"                    # 物品資訊的區塊分隔線
MAX_RETRY = 3                            # ctrl+c 最多重試次數
COPY_WAIT = 0.15                         # 每次 ctrl+c 之後等待剪貼簿更新的秒數

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORD_FILE = os.path.join(BASE_DIR, "item_records.txt")

# ---- 視覺反饋設定 ----
FLASH_SIZE = 45              # 特效視窗邊長（像素）
FLASH_COLOR = (0, 255, 102)  # 光環顏色 (R, G, B)
FLASH_STEPS = 4              # 動畫格數
FLASH_INTERVAL = 0.022       # 每格間隔（秒）

# 寫入時用來分隔各筆紀錄、並能夠回頭數出目前流水號的標記
RECORD_HEADER_PREFIX = "===== #"


def extract_top_block(text: str) -> str:
    """擷取最上面的第一個區塊（第一條分隔線之前的內容）。"""
    if not text:
        return ""
    block = text.split(SEPARATOR, 1)[0]
    return block.strip()


def get_next_serial() -> int:
    """讀取記錄檔，算出下一個流水號（目前筆數 + 1）。"""
    if not os.path.exists(RECORD_FILE):
        return 1
    count = 0
    with open(RECORD_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(RECORD_HEADER_PREFIX):
                count += 1
    return count + 1


def append_record(serial: int, block: str) -> None:
    """把一筆紀錄附加到記錄檔。"""
    with open(RECORD_FILE, "a", encoding="utf-8") as f:
        f.write(f"{RECORD_HEADER_PREFIX}{serial} =====\n")
        f.write(block + "\n")
        f.write("\n")


# ===== Win32 視覺反饋（純 ctypes，不依賴 tkinter）=====
_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32

# 視窗樣式常數
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020   # 滑鼠點擊穿透
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080    # 不顯示於工作列
_WS_EX_NOACTIVATE = 0x08000000    # 不搶焦點
_SW_SHOWNOACTIVATE = 4
_LWA_COLORKEY = 0x00000001
_LWA_ALPHA = 0x00000002
_NULL_BRUSH = 5
_PS_SOLID = 0
_PM_REMOVE = 0x0001

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT, wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
)


class _WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", ctypes.c_uint),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


# 設定函式簽章，避免 64 位元下的 handle 截斷
_user32.DefWindowProcW.restype = _LRESULT
_user32.DefWindowProcW.argtypes = [
    wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM
]
_user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASS)]
_user32.RegisterClassW.restype = wintypes.ATOM
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
]
_user32.SetLayeredWindowAttributes.argtypes = [
    wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD
]
_user32.GetDC.restype = wintypes.HDC
_user32.GetDC.argtypes = [wintypes.HWND]
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.CreatePen.restype = wintypes.HPEN
_gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
_gdi32.GetStockObject.restype = wintypes.HGDIOBJ
_gdi32.SelectObject.restype = wintypes.HGDIOBJ
_gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi32.Ellipse.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int
]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
_user32.PeekMessageW.argtypes = [
    ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint
]
_user32.TranslateMessage.argtypes = [ctypes.c_void_p]
_user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
ctypes.windll.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
ctypes.windll.kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

_flash_counter = itertools.count()


def _rgb(color) -> int:
    r, g, b = color
    return r | (g << 8) | (b << 16)


def get_cursor_pos() -> tuple:
    """取得滑鼠目前螢幕座標 (x, y)。"""
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _flash_worker(x: int, y: int) -> None:
    """以 Win32 分層視窗在 (x, y) 畫一圈向外擴張並淡出的光環。"""
    hwnd = None
    class_name = f"PoEFlash_{threading.get_ident()}_{next(_flash_counter)}"
    wndproc = _WNDPROC(_user32.DefWindowProcW)  # 保留參考避免被 GC
    wc = _WNDCLASS()
    registered = False
    try:
        hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        if not _user32.RegisterClassW(ctypes.byref(wc)):
            return
        registered = True

        ex_style = (
            _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_TOPMOST
            | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE
        )
        left = x - FLASH_SIZE // 2
        top = y - FLASH_SIZE // 2
        hwnd = _user32.CreateWindowExW(
            ex_style, class_name, None, _WS_POPUP,
            left, top, FLASH_SIZE, FLASH_SIZE,
            None, None, hinst, None,
        )
        if not hwnd:
            return

        # 黑色作為透明色鍵，整體再套用 alpha 控制淡出
        colorkey = _rgb((0, 0, 0))
        _user32.SetLayeredWindowAttributes(
            hwnd, colorkey, 255, _LWA_COLORKEY | _LWA_ALPHA
        )
        _user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)

        null_brush = _gdi32.GetStockObject(_NULL_BRUSH)
        pen_color = _rgb(FLASH_COLOR)
        msg = wintypes.MSG()

        for step in range(FLASH_STEPS + 1):
            progress = step / FLASH_STEPS
            hdc = _user32.GetDC(hwnd)
            try:
                # 光環逐步向外擴張、線條變細
                pad = int(4 + progress * (FLASH_SIZE / 2 - 6))
                pen_w = max(1, int(6 * (1 - progress)))
                pen = _gdi32.CreatePen(_PS_SOLID, pen_w, pen_color)
                old_pen = _gdi32.SelectObject(hdc, pen)
                old_brush = _gdi32.SelectObject(hdc, null_brush)
                _gdi32.Ellipse(hdc, pad, pad, FLASH_SIZE - pad, FLASH_SIZE - pad)
                _gdi32.SelectObject(hdc, old_pen)
                _gdi32.SelectObject(hdc, old_brush)
                _gdi32.DeleteObject(pen)
            finally:
                _user32.ReleaseDC(hwnd, hdc)

            alpha = max(0, int(255 * (1 - progress)))
            _user32.SetLayeredWindowAttributes(
                hwnd, colorkey, alpha, _LWA_COLORKEY | _LWA_ALPHA
            )
            # 抽空訊息佇列讓視窗保持回應
            while _user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, _PM_REMOVE):
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(FLASH_INTERVAL)
    except Exception as exc:  # 特效失敗不應影響主要記錄流程
        print(f"[!] 視覺反饋顯示失敗：{exc}")
    finally:
        if hwnd:
            _user32.DestroyWindow(hwnd)
        if registered:
            _user32.UnregisterClassW(class_name, None)


def flash_at_cursor() -> None:
    """在滑鼠當前位置顯示一次成功特效（非阻塞）。"""
    try:
        x, y = get_cursor_pos()
    except Exception as exc:
        print(f"[!] 取得游標位置失敗：{exc}")
        return
    threading.Thread(target=_flash_worker, args=(x, y), daemon=True).start()


def copy_with_retry() -> str:
    """清空剪貼簿後觸發 ctrl+c，檢查內容，必要時重試。回傳剪貼簿內容（可能為空字串）。"""
    for attempt in range(1, MAX_RETRY + 1):
        # 清空剪貼簿，避免誤用之前的值
        pyperclip.copy("")
        time.sleep(0.05)

        keyboard.send("ctrl+c")
        time.sleep(COPY_WAIT)

        content = pyperclip.paste()
        if content and content.strip():
            return content

        print(f"[!] 第 {attempt} 次 ctrl+c 後剪貼簿仍為空，重試中...")

    return ""


def on_hotkey() -> None:
    content = copy_with_retry()
    if not content:
        print("[x] 重試三次後剪貼簿仍無內容，放棄寫入。")
        return

    block = extract_top_block(content)
    if not block:
        print("[x] 擷取後內容為空，放棄寫入。")
        return

    serial = get_next_serial()
    append_record(serial, block)
    flash_at_cursor()  # 成功寫入後在游標處亮特效
    print(f"[v] 已寫入第 {serial} 筆：")
    print(block)
    print("-" * 30)


def main() -> None:
    print("物品資訊記錄器已啟動。")
    print(f"記錄檔：{RECORD_FILE}")
    print(f"按下 '{HOTKEY}' 進行擷取，按 Esc 結束程式。")
    keyboard.add_hotkey(HOTKEY, on_hotkey)
    keyboard.wait("esc")
    print("程式結束。")


if __name__ == "__main__":
    main()
