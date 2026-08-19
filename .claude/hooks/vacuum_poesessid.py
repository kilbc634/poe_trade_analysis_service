#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""UserPromptSubmit hook：把手貼在 setting.py 裡的 POESESSID 搬進 .poesessid。

為什麼需要這支：使用者的習慣是把新的 POESESSID 貼進 `setting.py` 的
`os.getenv('POESESSID', '<這裡>')`，但 setting.py 在版控裡，token 留在那邊
就是一個隨時可能被 `git add .` 帶上 GitHub 的秘密。這支在每次送出訊息時
把值搬到 gitignored 的 `.poesessid`（唯一存放地點），並把 setting.py 清空，
所以工作區永遠是乾淨的、而 token 依然隨時取用得到。
（取用方式與這個安排的來由：skills/open-poe-trade 的 Step 1、
skills/poe-trade-query/common/tricks.md 的「POESESSID 的存放」。）

守則（順序有意義，別調換）：
- **空值絕不覆蓋**：setting.py 沒有值就什麼都不做，不會把既有的 .poesessid 洗掉。
- **不做任何格式檢查**（使用者指定 2026-08-19）：token 有沒有效只有打 API 才知道，
  也無法預測官方哪天換格式。而且對 AI 來說「過期」和「格式錯」是分不出來的，
  本來就不該分——一律當作**失效**，走既有的失效流程（請使用者補、或 fallback，
  見 skills/poe-trade-query/common/tricks.md）。所以這支只管搬運，不當守門員。
- **先寫新檔、驗證讀回、才清空 setting.py**：任一步失敗就保留原狀，不會兩邊都沒有。
- **絕不印出 token 本身**：這支的 stdout 會進 Claude 的 context。
- **stdout 一律用 ASCII**：Windows console 的 codepage 會把 UTF-8 中文轉成亂碼，
  而這段字是要給模型讀的，不能賭終端機的編碼。
- **絕不阻擋 prompt**：任何例外都靜靜 exit 0（hook 壞掉不該讓使用者不能送訊息）。

環境變數 POESESSID 若已設定，setting.py 會優先用它——那是刻意的臨時覆蓋管道，
與本檔無關。
"""
import os
import re
import sys

# .claude/hooks/vacuum_poesessid.py -> 專案根目錄（不依賴 CWD，hook 的工作目錄不保證）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTING = os.path.join(ROOT, 'setting.py')
TARGET = os.path.join(ROOT, '.poesessid')

# 只認 setting.py 那一行的 getenv 預設值；引號種類與空白都放寬
PATTERN = re.compile(
    r"""(POESESSID\s*=\s*os\.getenv\(\s*['"]POESESSID['"]\s*,\s*)(['"])([^'"]*)(\2\s*\))"""
)


def main():
    if not os.path.isfile(SETTING):
        return

    with open(SETTING, encoding='utf-8', newline='') as f:
        src = f.read()

    m = PATTERN.search(src)
    if not m:
        return

    token = m.group(3).strip()
    if not token:
        return                      # 空值不覆蓋——唯一的守門條件

    # 1) 先落地新值（同目錄暫存檔 + os.replace；目標不存在就是單純建檔）
    tmp = TARGET + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(token + '\n')
    os.replace(tmp, TARGET)

    # 2) 驗證讀回一致，不一致就別動 setting.py（token 至少還在原處）
    with open(TARGET, encoding='utf-8') as f:
        if f.read().strip() != token:
            return

    # 3) 清空 setting.py 的預設值。newline='' 讀寫，保留原本的 CRLF
    cleaned = src[:m.start()] + m.group(1) + m.group(2) + m.group(2) + m.group(4)[1:] + src[m.end():]
    with open(SETTING, 'w', encoding='utf-8', newline='') as f:
        f.write(cleaned)

    # 進 Claude context 的通知：只講發生了什麼，不含 token 本身
    print('[poesessid] The user just pasted a fresh POESESSID: moved into .poesessid '
          '(gitignored) and setting.py has been re-blanked. Read it only via shell '
          'substitution, gated -- `test -s .poesessid && curl ... "Cookie: POESESSID=$(cat '
          '.poesessid)"` in Bash (ungated, a missing file goes out ANONYMOUS and looks like '
          'success), or (Get-Content .poesessid -Raw).Trim() in PowerShell. Never read the '
          'value into the conversation. Details: the open-poe-trade skill, Step 1.')


if __name__ == '__main__':
    try:
        main()
    except Exception:               # hook 壞掉不該讓使用者送不出訊息
        pass
    sys.exit(0)
