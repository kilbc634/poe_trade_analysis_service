import time

# wholesalers(一般搜尋輪詢購買) → depositor(背包存倉) 串成一次完整循環
from wholesalers import main as wholesalers_main
from depositor import main as depositor_main

MIN_TIMES = 1
MAX_TIMES = 100
START_DELAY = 10   # 開始前倒數秒數
CYCLE_GAP = 10     # 每次循環之間的間隔秒數


def ask_times():
    """互動詢問要執行的次數，限制 1~100，含防呆。"""
    while True:
        raw = input(f"請輸入要執行的次數 ({MIN_TIMES}~{MAX_TIMES}): ").strip()
        try:
            n = int(raw)
        except ValueError:
            print("  ⚠ 請輸入整數")
            continue
        if MIN_TIMES <= n <= MAX_TIMES:
            return n
        print(f"  ⚠ 超出範圍，請輸入 {MIN_TIMES}~{MAX_TIMES}")


def countdown(secs, msg):
    for i in range(secs, 0, -1):
        print(f"\r{msg} {i} 秒...   ", end="", flush=True)
        time.sleep(1)
    print()


def main():
    n = ask_times()
    print(f"將連續執行 {n} 次：每次 = wholesalers(購買) → depositor(存倉)")
    countdown(START_DELAY, "開始前倒數")

    for i in range(n):
        print(f"\n========== 第 {i + 1}/{n} 次循環開始 ==========")
        wholesalers_main()   # 一般搜尋輪詢購買（內部跑固定輪數）
        depositor_main()     # 把背包前 40 格存入倉庫
        print(f"========== 第 {i + 1}/{n} 次循環完成 ==========")

        if i < n - 1:
            countdown(CYCLE_GAP, "下一次循環倒數")

    print("\n[ALL DONE] 全部循環執行完畢")


if __name__ == "__main__":
    main()
