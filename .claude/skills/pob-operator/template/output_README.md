# output/

分析產出的暫存區：腳本、量測資料、報告。

**可以隨時整個清空**，裡面沒有 `pob-headless` 運作所需的東西。

沒有規定格式。慣例只有一條：**任何跑出來的東西寫在這裡，不要丟在入口根目錄**，
免得跟 `pob.py` / `make_boot.py` / `headless_boot.lua` 混在一起。

在這裡跑腳本要 import `pob`，把上層目錄加進路徑：

```python
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pob import PoB
```

或直接從入口根目錄跑（`python output/某腳本.py`）。
