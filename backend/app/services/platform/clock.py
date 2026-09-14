"""時間相關的共用常數。

存在的理由：先前 `TAIPEI_TZ` 定義在 `services/matching.py`（舊零股模擬器的
撮合引擎）裡，於是 ml/training_runner 和 backfill_status 這兩個新系統的模組
為了一個時區常數，把整個 333 行的撮合邏輯拉進依賴圖。

時區不屬於任何一個業務模組，放平台層。
"""

from zoneinfo import ZoneInfo

# 台股所有時間判斷的基準。不要用 datetime.now() 的本機時區——容器跑在 UTC，
# 「今天是哪一天」會在台北時間 08:00 前算錯一天
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
