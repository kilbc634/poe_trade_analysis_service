# -*- coding: utf-8 -*-
"""自動點通貨製作「單詞綴稀有珠寶」（給 Subsume the Source 吞用的命中深淵珠寶）。

流程（每一步都先用 Ctrl+C 讀物品，再決定下一顆通貨）：
    普通   → 蛻變石
    魔法   → 目標詞綴達標 → 富豪石
             只有前綴     → 增幅石
             其他         → 改造石
    稀有   → 目標還在且不只一條 → 無效石
             目標還在且只剩一條 → 完成，停下來等你換基底
             目標被洗掉         → 重鑄石，從頭再來

用法：
    python jewel_crafter.py setup      設定點擊位置（F10 記錄目前鼠標位置並輸入編號，F9 結束）
    python jewel_crafter.py test       把鼠標停在物品上按 F10，印出腳本讀到的內容與下一步判斷（不會點任何通貨）
    python jewel_crafter.py run        開始製作（F10 開始／完成後換好基底再按 F10 做下一顆，F9 隨時中止）
                                       畫面只印開始、完成、停止與累計；每一步的紀錄寫在 jewel_crafter_logs/run-<時間>.log
    python jewel_crafter.py selftest   不碰遊戲，只驗證解析與判斷邏輯

位置與參數存在同資料夾的 jewel_crafter.ini（第一次執行會自動建立，已 gitignore）。
"""
import configparser
import os
import queue
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INI = os.path.join(HERE, "jewel_crafter.ini")
LOG_DIR = os.path.join(HERE, "jewel_crafter_logs")

# 編號 → (ini 鍵, 顯示名稱)
SLOTS = {
    "1": ("item", "物品（中間放基底的那一格）"),
    "2": ("transmutation", "蛻變石 Orb of Transmutation"),
    "3": ("alteration", "改造石 Orb of Alteration"),
    "4": ("augmentation", "增幅石 Orb of Augmentation"),
    "5": ("regal", "富豪石 Regal Orb"),
    "6": ("annulment", "無效石 Orb of Annulment"),
    "7": ("scouring", "重鑄石 Orb of Scouring"),
}
DEFAULTS = {
    "target": {
        # 目標詞綴：第一個括號要抓到數值
        "regex": r"^\+(\d+)(?:\(\d+-\d+\))? to Accuracy Rating$",
        "min_value": "290",
        "base_name": "Searching Eye Jewel",
    },
    "run": {
        "window_title": "Path of Exile",
        "max_alterations": "6000",      # 單次執行最多用幾顆改造石
        "step_delay": "0.27",           # 對物品按完左鍵到送出 Ctrl+C 之間的等待（秒）；太短會讀到伺服器還沒更新的舊內容
        "currency_hover_delay": "0.10", # 鼠標停到通貨上之後，等多久才按右鍵（秒）；怕 lag 沒點到就調大
        "after_pick_delay": "0.10",     # 右鍵放開之後，鼠標在通貨上多停多久才離開（秒）
        "move_duration": "0.10",        # 滑進格子的時間（秒）
        "approach_offset": "55",        # 先瞬移到離目標多遠的地方再滑進去（像素）
        "jitter": "6",                  # 目標點的隨機偏移（像素）
        "allow_scour_at_start": "no",   # 一開始放上去的稀有物品若沒有目標詞綴，是否允許直接重鑄
    },
}


# ---------------------------------------------------------------------------
# 設定檔
# ---------------------------------------------------------------------------
def load_config():
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(INI, encoding="utf-8")
    changed = False
    for sec, kv in DEFAULTS.items():
        if not cfg.has_section(sec):
            cfg.add_section(sec); changed = True
        for k, v in kv.items():
            if not cfg.has_option(sec, k):
                cfg.set(sec, k, v); changed = True
    if not cfg.has_section("positions"):
        cfg.add_section("positions"); changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    with open(INI, "w", encoding="utf-8") as f:
        cfg.write(f)


def get_pos(cfg, key):
    raw = cfg.get("positions", key, fallback="")
    m = re.match(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*$", raw)
    return (int(m.group(1)), int(m.group(2))) if m else None


# ---------------------------------------------------------------------------
# 物品文字解析（純函式，不碰遊戲）
# ---------------------------------------------------------------------------
class Item:
    def __init__(self):
        self.rarity = None          # Normal / Magic / Rare / Unique
        self.name_lines = []
        self.mods = []              # [{"kind": "prefix"|"suffix"|"unknown", "lines": [...]}]
        self.advanced = False
        self.flags = set()          # corrupted / unidentified / mirrored
        self.target_value = None
        self.has_prefix = None      # None = 判斷不出來
        self.has_suffix = None

    @property
    def nmods(self):
        return len(self.mods)

    def describe(self):
        mods = " | ".join("%s:%s" % (m["kind"][0], " / ".join(m["lines"])) for m in self.mods) or "(無詞綴)"
        return "%s [%s] 詞綴 %d 條 目標值=%s 前綴=%s 後綴=%s%s :: %s" % (
            " ".join(self.name_lines), self.rarity, self.nmods, self.target_value, self.has_prefix, self.has_suffix,
            (" 旗標=" + ",".join(sorted(self.flags))) if self.flags else "", mods)


SKIP_SUFFIXES = ("(implicit)", "(enchant)", "(scourge)", "(crucible)")


def parse_item(text, target_regex, base_name):
    """把 Ctrl+C 複製出來的文字解析成 Item；格式不對回傳 None。
    文字裡有 `{ Prefix Modifier … }` 這種標示時用它數詞綴，沒有時退回用物品名稱與行數判斷。"""
    if not text or "Rarity:" not in text:
        return None
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n")]
    sections, cur = [], []
    for l in lines:
        if l.strip() == "--------":
            sections.append(cur); cur = []
        else:
            cur.append(l)
    sections.append(cur)
    it = Item()
    head = sections[0]
    for i, l in enumerate(head):
        if l.startswith("Rarity:"):
            it.rarity = l.split(":", 1)[1].strip()
            it.name_lines = [x for x in head[i + 1:] if x.strip()]
    if not it.rarity:
        return None
    body = []
    for sec in sections[1:]:
        for l in sec:
            s = l.strip()
            if s == "Corrupted":
                it.flags.add("corrupted")
            elif s == "Unidentified":
                it.flags.add("unidentified")
            elif s == "Mirrored":
                it.flags.add("mirrored")
        body.append(sec)
    all_lines = [l.strip() for sec in body for l in sec if l.strip()]
    it.advanced = any(l.startswith("{") and "Modifier" in l for l in all_lines)
    rx = re.compile(target_regex)
    if it.advanced:
        cur_mod = None
        SEP = "\x00"                                               # 區段邊界：一條詞綴的內容不會跨區段
        marked = [x for sec in body for x in ([SEP] + [l.strip() for l in sec if l.strip()])]
        for l in marked:
            if l == SEP:
                cur_mod = None
            elif l.startswith("{") and l.endswith("}"):
                low = l.lower()
                if "prefix modifier" in low:
                    cur_mod = {"kind": "prefix", "lines": []}; it.mods.append(cur_mod)
                elif "suffix modifier" in low:
                    cur_mod = {"kind": "suffix", "lines": []}; it.mods.append(cur_mod)
                else:
                    cur_mod = {"kind": "other", "lines": []}      # 隱性、附魔等，不算在詞綴數裡
            elif cur_mod is not None:
                if l.startswith("(") and l.endswith(")"):
                    continue                                       # 詞綴底下的說明小字，例如 (Recently refers to …)
                cur_mod["lines"].append(l)
        it.mods = [m for m in it.mods if m["kind"] in ("prefix", "suffix")]
        it.has_prefix = any(m["kind"] == "prefix" for m in it.mods)
        it.has_suffix = any(m["kind"] == "suffix" for m in it.mods)
    else:
        # 一般模式：詞綴在最後一個「不是旗標」的區段，一行算一條
        mod_sec = []
        for sec in reversed(body):
            cand = [l.strip() for l in sec if l.strip()]
            # 旗標與物品最下面的操作說明不是詞綴
            cand = [c for c in cand if c not in ("Corrupted", "Mirrored", "Unidentified")
                    and not c.startswith(("Place into", "Right click", "Shift click"))]
            if not cand:
                continue
            if any(c.startswith("Item Level:") for c in cand) or cand == ["Abyss"]:
                break                                              # 走到物品等級區段還沒遇到詞綴 = 沒有詞綴
            mod_sec = cand
            break
        for l in mod_sec:
            if l.endswith(SKIP_SUFFIXES) or l.startswith("Place into"):
                continue
            it.mods.append({"kind": "unknown", "lines": [l]})
        if it.rarity == "Magic" and it.name_lines and base_name and base_name in it.name_lines[0]:
            before, after = it.name_lines[0].split(base_name, 1)
            it.has_prefix = bool(before.strip())
            it.has_suffix = after.strip().startswith("of ")
    for m in it.mods:
        for l in m["lines"]:
            g = rx.match(l)
            if g:
                v = int(g.group(1))
                it.target_value = v if it.target_value is None else max(it.target_value, v)
    return it


def decide(it, min_value, started_by_script=True, allow_scour_at_start=False):
    """回傳 (動作, 說明)。動作：transmutation / alteration / augmentation / regal / annulment / scouring / done / stop"""
    if it is None:
        return "stop", "讀不到物品文字"
    if it.flags:
        return "stop", "物品有不能處理的狀態：" + ",".join(sorted(it.flags))
    hit = it.target_value is not None and it.target_value >= min_value
    if it.rarity == "Normal":
        return "transmutation", "普通物品，先變魔法"
    if it.rarity == "Magic":
        if hit:
            return "regal", "目標達標（%d），升稀有" % it.target_value
        if it.nmods == 1 and it.has_suffix is False:
            return "augmentation", "只有前綴，補一條後綴"
        return "alteration", "沒中，重洗"
    if it.rarity == "Rare":
        if hit and it.nmods == 1:
            return "done", "完成：只剩目標詞綴（%d）" % it.target_value
        if hit:
            return "annulment", "目標還在，還有 %d 條要洗掉" % (it.nmods - 1)
        if not started_by_script and not allow_scour_at_start:
            return "stop", "一開始放的稀有物品沒有達標的目標詞綴；確定要重鑄它的話把 allow_scour_at_start 設成 yes"
        return "scouring", "目標被洗掉了，重鑄重來"
    return "stop", "不支援的稀有度：%s" % it.rarity


# ---------------------------------------------------------------------------
# 與遊戲互動
# ---------------------------------------------------------------------------
class Game:
    def __init__(self, cfg):
        from ahk import AHK
        try:
            self.ahk = AHK()
        except Exception:
            self.ahk = AHK(executable_path=r"C:\Program Files\AutoHotkey\AutoHotkey.exe")
        self.cfg = cfg
        r = cfg["run"]
        self.title = r.get("window_title")
        self.step_delay = r.getfloat("step_delay")
        self.currency_hover_delay = r.getfloat("currency_hover_delay")
        self.after_pick_delay = r.getfloat("after_pick_delay")
        self.move_duration = r.getfloat("move_duration")
        self.offset = r.getint("approach_offset")
        self.jitter = r.getint("jitter")
        # 一律用 Ctrl+C，不碰 Alt：按住 Alt 會讓物品說明視窗固定在畫面上，
        # 而且手上拿著改造石時按 Alt 會被遊戲切換成增幅石。
        self.copy_keys = "^c"
        self.events = queue.Queue()
        self.abort = False

    # --- 熱鍵 ---
    def start_hotkeys(self):
        self.ahk.add_hotkey("F10", callback=lambda: self.events.put("F10"))
        self.ahk.add_hotkey("F9", callback=self._on_f9)
        self.ahk.start_hotkeys()

    def _on_f9(self):
        self.abort = True
        self.events.put("F9")

    def wait_key(self):
        return self.events.get()

    # --- 滑鼠 ---
    def game_active(self):
        try:
            w = self.ahk.active_window
            return bool(w) and self.title.lower() in (w.title or "").lower()
        except Exception:
            return False

    def glide_to(self, pos):
        """先瞬移到目標旁邊，再先快後慢滑進去，最後小晃一下，確保遊戲判定為懸停。"""
        tx = pos[0] + random.randint(-self.jitter, self.jitter)
        ty = pos[1] + random.randint(-self.jitter, self.jitter)
        dx, dy = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
        sx, sy = tx + dx * self.offset, ty + dy * self.offset
        self.ahk.mouse_move(sx, sy, speed=0)
        steps = 8
        for i in range(1, steps + 1):
            t = i / steps
            e = 1 - (1 - t) * (1 - t)
            self.ahk.mouse_move(int(sx + (tx - sx) * e), int(sy + (ty - sy) * e), speed=0)
            time.sleep(self.move_duration / steps)
        self.ahk.mouse_move(tx + random.choice([-2, 2]), ty + random.choice([-1, 1]), speed=0)
        time.sleep(0.02)
        self.ahk.mouse_move(tx, ty, speed=0)
        time.sleep(0.03)

    def wiggle(self):
        x, y = self.ahk.mouse_position
        for d in ((3, 0), (0, 3), (-3, 0), (0, 0)):
            self.ahk.mouse_move(x + d[0], y + d[1], speed=0)
            time.sleep(0.02)

    def click(self, button):
        b = "RButton" if button == "right" else "LButton"
        self.ahk.send_input("{%s down}" % b)
        time.sleep(random.uniform(0.04, 0.07))
        self.ahk.send_input("{%s up}" % b)
        time.sleep(random.uniform(0.04, 0.07))

    # --- 讀物品 ---
    def read_item(self, target_regex, base_name, expect_change_from=None):
        """鼠標必須已經停在物品上。回傳 (Item 或 None, 原始文字)。"""
        text = ""
        for attempt in range(4):
            self.ahk.set_clipboard("")
            self.ahk.send_input(self.copy_keys)
            t0 = time.time()
            while time.time() - t0 < 0.4:
                text = self.ahk.get_clipboard() or ""
                if "Rarity:" in text:
                    break
                time.sleep(0.03)
            if "Rarity:" in text and (expect_change_from is None or text != expect_change_from or attempt >= 1):
                break
            self.wiggle()                       # 沒讀到（或內容還沒更新）→ 晃一下再讀
            time.sleep(0.08)
        return parse_item(text, target_regex, base_name), text

    def use_currency(self, cur_pos, item_pos):
        self.glide_to(cur_pos)
        time.sleep(self.currency_hover_delay + random.uniform(0, 0.03))   # 讓遊戲先判定懸停，再按右鍵
        self.click("right")
        time.sleep(self.after_pick_delay)                                 # 確定遊戲吃到右鍵之後才離開通貨格
        self.glide_to(item_pos)
        self.click("left")
        time.sleep(self.step_delay)


# ---------------------------------------------------------------------------
# 模式
# ---------------------------------------------------------------------------
def mode_setup(cfg):
    g = Game(cfg)
    g.start_hotkeys()
    menu = "\n".join("%s = %s" % (k, v[1]) for k, v in SLOTS.items())
    print("== 設定模式 ==\n把鼠標移到位置上按 F10，輸入編號；全部設完按 F9 結束。\n" + menu)
    while True:
        ev = g.wait_key()
        if ev == "F9":
            break
        x, y = g.ahk.mouse_position
        ans = g.ahk.input_box(prompt="鼠標位置 (%d, %d)\n這個位置是什麼？輸入編號：\n\n%s" % (x, y, menu), title="jewel_crafter setup",
                              width=460, height=380)
        ans = (ans or "").strip()
        if ans not in SLOTS:
            print("  略過（沒有這個編號：%r）" % ans)
            continue
        key, label = SLOTS[ans]
        cfg.set("positions", key, "%d, %d" % (x, y))
        save_config(cfg)
        print("  已記錄 %s = (%d, %d)  %s" % (ans, x, y, label))
    g.ahk.stop_hotkeys()
    print("\n目前的設定：")
    for k, (key, label) in SLOTS.items():
        print("  %s %-14s %s  %s" % (k, key, get_pos(cfg, key) or "（未設定）", label))
    print("設定檔：" + INI)


def mode_test(cfg):
    g = Game(cfg)
    g.start_hotkeys()
    t = cfg["target"]
    print("== 測試模式 ==\n把鼠標停在遊戲裡的物品上按 F10（不會點任何通貨），F9 結束。")
    while True:
        if g.wait_key() == "F9":
            break
        it, raw = g.read_item(t.get("regex"), t.get("base_name"))
        print("-" * 60 + "\n" + (raw.strip() or "(剪貼簿是空的)") + "\n" + "-" * 60)
        if it is None:
            print("解析失敗：沒有讀到物品文字。確認鼠標停在物品上、遊戲視窗在最前面。")
            continue
        act, why = decide(it, t.getint("min_value"), started_by_script=False,
                          allow_scour_at_start=cfg["run"].getboolean("allow_scour_at_start"))
        print("解析：" + it.describe())
        print("詞綴標示：%s｜下一步會是：%s（%s）" % ("有（照標示數詞綴）" if it.advanced else "沒有（照名稱與行數判斷）", act, why))
    g.ahk.stop_hotkeys()


def mode_run(cfg):
    pos = {key: get_pos(cfg, key) for key, _ in SLOTS.values()}
    missing = [label for key, label in SLOTS.values() if not pos[key]]
    if missing:
        sys.exit("以下位置還沒設定，先跑 `python jewel_crafter.py setup`：\n  " + "\n  ".join(missing))
    g = Game(cfg)
    g.start_hotkeys()
    t, r = cfg["target"], cfg["run"]
    rx, base, min_value = t.get("regex"), t.get("base_name"), t.getint("min_value")
    max_alts = r.getint("max_alterations")
    allow_scour0 = r.getboolean("allow_scour_at_start")
    total = {}
    made = 0
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, time.strftime("run-%Y%m%d-%H%M%S.log"))
    logf = open(log_path, "w", encoding="utf-8")

    def log(msg):
        """逐步紀錄只寫檔案，不印到畫面"""
        logf.write(time.strftime("%H:%M:%S ") + msg + "\n")
        logf.flush()

    def say(msg):
        """重要事件：畫面和檔案都有"""
        print(msg)
        log(msg.strip())

    print("== 製作模式 ==  目標：%s >= %d" % (rx, min_value))
    print("逐步紀錄寫在：" + log_path)
    print("遊戲切到通貨頁、基底放好後按 F10 開始；F9 隨時中止。")
    log("target %s >= %d | settings %s" % (rx, min_value, dict(r)))
    try:
        while True:
            if g.wait_key() == "F9":
                break
            g.abort = False
            used = {}
            ours = False            # 這顆基底是不是已經由腳本動過（決定能不能重鑄）
            same = 0
            reason = None
            g.glide_to(pos["item"])
            it, raw = g.read_item(rx, base)
            log("---- 開始一顆：" + (it.describe() if it else "讀不到物品"))
            while True:
                if g.abort:
                    reason = "使用者按 F9 中止"; break
                if not g.game_active():
                    reason = "遊戲視窗不在最前面"; break
                act, why = decide(it, min_value, started_by_script=ours, allow_scour_at_start=allow_scour0)
                if act == "done":
                    made += 1
                    say("  ★ %s｜這顆用了 %s" % (why, used or "0 顆通貨"))
                    for _ in range(3):
                        g.ahk.sound_beep(880, 150)
                    break
                if act == "stop":
                    reason = why; break
                if act == "alteration" and total.get("alteration", 0) >= max_alts:
                    reason = "改造石用量達到上限 max_alterations=%d" % max_alts; break
                before, before_n, before_r = raw, it.nmods, it.rarity
                g.use_currency(pos[act], pos["item"])
                it, raw = g.read_item(rx, base, expect_change_from=before)
                used[act] = used.get(act, 0) + 1
                total[act] = total.get(act, 0) + 1
                ours = True
                log("%-13s #%-4d → %s" % (act, used[act], it.describe() if it else "讀不到"))
                # --- 驗證這一步真的生效，沒生效通常是通貨用完或點歪 ---
                if it is None:
                    reason = "用完 %s 之後讀不到物品" % act; break
                expect = {"transmutation": lambda: it.rarity == "Magic", "regal": lambda: it.rarity == "Rare",
                          "scouring": lambda: it.rarity == "Normal", "annulment": lambda: it.nmods == before_n - 1,
                          "augmentation": lambda: it.nmods == before_n + 1}.get(act)
                if expect and not expect():
                    reason = "%s 沒有生效（稀有度 %s→%s、詞綴 %d→%d）；通貨用完了或位置點歪了" % (act, before_r, it.rarity, before_n, it.nmods); break
                if act == "alteration":
                    same = same + 1 if raw == before else 0
                    if same >= 3:
                        reason = "連續 3 次改造石後物品都沒變；通貨用完了或位置點歪了"; break
            if reason:
                say("  ■ 停止：%s｜這顆已用 %s" % (reason, used))
            say("累計：完成 %d 顆，通貨用量 %s" % (made, total))
            print("換好基底後按 F10 繼續，F9 結束。")
    finally:
        g.ahk.stop_hotkeys()
        log("結束。累計：完成 %d 顆，通貨用量 %s" % (made, total))
        logf.close()


# ---------------------------------------------------------------------------
# 自我測試（不碰遊戲）
# ---------------------------------------------------------------------------
def mode_selftest(cfg=None):
    rx, base = DEFAULTS["target"]["regex"], DEFAULTS["target"]["base_name"]
    head = "Item Class: Abyss Jewels\nRarity: %s\n%s\n--------\nAbyss\n--------\nItem Level: 86\n"
    tail = "--------\nPlace into an Abyssal Socket on an Item or into an allocated Jewel Socket on the Passive Skill Tree. Right click to remove from the Socket.\n"
    def adv(rarity, name, mods):
        body = "".join('{ %s Modifier "%s" (Tier: 1) }\n%s\n' % (k, n, l) for k, n, l in mods)
        return head % (rarity, name) + ("--------\n" + body if mods else "") + tail
    def plain(rarity, name, mods):
        return head % (rarity, name) + ("--------\n" + "\n".join(mods) + "\n" if mods else "") + tail
    ACC = "+295(241-300) to Accuracy Rating"
    cases = [
        ("普通", adv("Normal", "Searching Eye Jewel", []), "transmutation"),
        ("魔法 只有前綴", adv("Magic", "Hale Searching Eye Jewel", [("Prefix", "Hale", "+23(21-25) to maximum Life")]), "augmentation"),
        ("魔法 只有後綴 沒中", adv("Magic", "Searching Eye Jewel of Strength", [("Suffix", "of Strength", "+14(12-16) to Strength")]), "alteration"),
        ("魔法 前後綴 沒中", adv("Magic", "Hale Searching Eye Jewel of Strength", [("Prefix", "Hale", "+23(21-25) to maximum Life"), ("Suffix", "of Strength", "+14(12-16) to Strength")]), "alteration"),
        ("魔法 命中但數值不夠", adv("Magic", "Searching Eye Jewel of the Deadeye", [("Suffix", "of the Deadeye", "+262(241-300) to Accuracy Rating")]), "alteration"),
        ("魔法 低階命中", adv("Magic", "Searching Eye Jewel of the Ranger", [("Suffix", "of the Ranger", "+230(121-240) to Accuracy Rating")]), "alteration"),
        ("魔法 達標 單條", adv("Magic", "Searching Eye Jewel of the Deadeye", [("Suffix", "of the Deadeye", ACC)]), "regal"),
        ("魔法 達標 帶前綴", adv("Magic", "Hale Searching Eye Jewel of the Deadeye", [("Prefix", "Hale", "+23(21-25) to maximum Life"), ("Suffix", "of the Deadeye", ACC)]), "regal"),
        ("稀有 三條 目標在", adv("Rare", "Dire Gaze\nSearching Eye Jewel", [("Prefix", "Hale", "+23(21-25) to maximum Life"), ("Suffix", "of the Deadeye", ACC), ("Suffix", "of Strength", "+14(12-16) to Strength")]), "annulment"),
        ("稀有 兩條 目標在", adv("Rare", "Dire Gaze\nSearching Eye Jewel", [("Suffix", "of the Deadeye", ACC), ("Suffix", "of Strength", "+14(12-16) to Strength")]), "annulment"),
        ("稀有 只剩目標", adv("Rare", "Dire Gaze\nSearching Eye Jewel", [("Suffix", "of the Deadeye", ACC)]), "done"),
        ("稀有 目標被洗掉", adv("Rare", "Dire Gaze\nSearching Eye Jewel", [("Suffix", "of Strength", "+14(12-16) to Strength")]), "scouring"),
        ("一般模式 魔法 只有前綴", plain("Magic", "Hale Searching Eye Jewel", ["+23 to maximum Life"]), "augmentation"),
        ("一般模式 魔法 達標", plain("Magic", "Searching Eye Jewel of the Deadeye", ["+295 to Accuracy Rating"]), "regal"),
        ("一般模式 稀有 兩條", plain("Rare", "Dire Gaze\nSearching Eye Jewel", ["+295 to Accuracy Rating", "+14 to Strength"]), "annulment"),
        ("一般模式 稀有 只剩目標", plain("Rare", "Dire Gaze\nSearching Eye Jewel", ["+295 to Accuracy Rating"]), "done"),
        ("一般模式 普通", plain("Normal", "Searching Eye Jewel", []), "transmutation"),
        ("已腐化", adv("Rare", "Dire Gaze\nSearching Eye Jewel", [("Suffix", "of the Deadeye", ACC)]).replace(tail, "--------\nCorrupted\n" + tail), "stop"),
        ("召喚物命中不算", adv("Magic", "Searching Eye Jewel of X", [("Suffix", "of X", "Minions have +295(95-125) to Accuracy Rating")]), "alteration"),
    ]
    bad = 0
    for name, text, want in cases:
        it = parse_item(text, rx, base)
        act, why = decide(it, 290)
        ok = act == want
        bad += not ok
        print("%s %-22s → %-13s %s" % ("OK " if ok else "BAD", name, act, "" if ok else "(預期 %s) %s" % (want, it.describe() if it else None)))
    it = parse_item(cases[11][1], rx, base)
    a1 = decide(it, 290, started_by_script=False, allow_scour_at_start=False)[0]
    a2 = decide(it, 290, started_by_script=False, allow_scour_at_start=True)[0]
    ok = (a1, a2) == ("stop", "scouring")
    bad += not ok
    print("%s 開場稀有物品的重鑄保護 → %s / %s" % ("OK " if ok else "BAD", a1, a2))
    print("\n%d 項，%d 項失敗" % (len(cases) + 1, bad))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "selftest":
        mode_selftest()
    elif mode in ("setup", "test", "run"):
        {"setup": mode_setup, "test": mode_test, "run": mode_run}[mode](load_config())
    else:
        print(__doc__)
