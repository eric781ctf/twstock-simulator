"""策略條件的結構定義、驗證與判斷邏輯。條件存成 JSON list，每個條件是一個
dict，用 "type" 欄位分派。支援的條件類型：

- kd_value        {"type": "kd_value", "line": "k"|"d", "operator": "gt"|"lt"|"gte"|"lte", "value": number}
- kd_cross        {"type": "kd_cross", "direction": "golden"|"death"}         K/D 黃金交叉、死亡交叉
- ma_compare      {"type": "ma_compare", "fast": 5|20|60, "slow": 5|20|60, "operator": "gt"|"lt"}   均線多空排列
- price_vs_ma     {"type": "price_vs_ma", "period": 5|20|60, "operator": "gt"|"lt"}   收盤價相對均線
- streak          {"type": "streak", "direction": "up"|"down", "days": number}         連續漲跌天數
- cumulative_change {"type": "cumulative_change", "days": number, "operator": "gte"|"lte", "percent": number}  累積漲跌幅
"""

from app.models import DailyBar
from app.services.indicators import compute_kd_series, cumulative_change_percent, latest_ma, streak

VALID_TYPES = {"kd_value", "kd_cross", "ma_compare", "price_vs_ma", "streak", "cumulative_change"}
VALID_PERIODS = {5, 20, 60}
VALID_OPERATORS = {"gt", "lt", "gte", "lte"}


class ConditionValidationError(Exception):
    pass


def _require(cond: dict, key: str, expected_types: tuple):
    if key not in cond or not isinstance(cond[key], expected_types):
        raise ConditionValidationError(f"條件缺少或格式錯誤的欄位：{key}")
    return cond[key]


def validate_condition(cond: dict) -> None:
    if not isinstance(cond, dict) or "type" not in cond:
        raise ConditionValidationError("條件格式錯誤")
    t = cond["type"]
    if t not in VALID_TYPES:
        raise ConditionValidationError(f"不支援的條件類型：{t}")

    if t == "kd_value":
        line = _require(cond, "line", (str,))
        if line not in ("k", "d"):
            raise ConditionValidationError("kd_value 的 line 必須是 k 或 d")
        op = _require(cond, "operator", (str,))
        if op not in VALID_OPERATORS:
            raise ConditionValidationError("kd_value 的 operator 不合法")
        value = _require(cond, "value", (int, float))
        if not (0 <= value <= 100):
            raise ConditionValidationError("kd_value 的 value 必須介於 0~100")
    elif t == "kd_cross":
        direction = _require(cond, "direction", (str,))
        if direction not in ("golden", "death"):
            raise ConditionValidationError("kd_cross 的 direction 必須是 golden 或 death")
    elif t == "ma_compare":
        fast = _require(cond, "fast", (int,))
        slow = _require(cond, "slow", (int,))
        if fast not in VALID_PERIODS or slow not in VALID_PERIODS or fast == slow:
            raise ConditionValidationError("ma_compare 的 fast/slow 必須是 5/20/60 且不能相同")
        op = _require(cond, "operator", (str,))
        if op not in ("gt", "lt"):
            raise ConditionValidationError("ma_compare 的 operator 必須是 gt 或 lt")
    elif t == "price_vs_ma":
        period = _require(cond, "period", (int,))
        if period not in VALID_PERIODS:
            raise ConditionValidationError("price_vs_ma 的 period 必須是 5/20/60")
        op = _require(cond, "operator", (str,))
        if op not in ("gt", "lt"):
            raise ConditionValidationError("price_vs_ma 的 operator 必須是 gt 或 lt")
    elif t == "streak":
        direction = _require(cond, "direction", (str,))
        if direction not in ("up", "down"):
            raise ConditionValidationError("streak 的 direction 必須是 up 或 down")
        days = _require(cond, "days", (int,))
        if days < 1:
            raise ConditionValidationError("streak 的 days 必須 >= 1")
    elif t == "cumulative_change":
        days = _require(cond, "days", (int,))
        if days < 1:
            raise ConditionValidationError("cumulative_change 的 days 必須 >= 1")
        op = _require(cond, "operator", (str,))
        if op not in ("gte", "lte"):
            raise ConditionValidationError("cumulative_change 的 operator 必須是 gte 或 lte")
        _require(cond, "percent", (int, float))


def validate_conditions(conditions: list) -> None:
    if not isinstance(conditions, list):
        raise ConditionValidationError("條件必須是陣列")
    for cond in conditions:
        validate_condition(cond)


def _compare(value: float, operator: str, target: float) -> bool:
    if operator == "gt":
        return value > target
    if operator == "lt":
        return value < target
    if operator == "gte":
        return value >= target
    if operator == "lte":
        return value <= target
    return False


def evaluate_condition(cond: dict, bars: list[DailyBar]) -> bool:
    t = cond["type"]

    if t == "kd_value":
        series = compute_kd_series(bars)
        if not series:
            return False
        k, d = series[-1]
        value = k if cond["line"] == "k" else d
        return _compare(value, cond["operator"], cond["value"])

    if t == "kd_cross":
        series = compute_kd_series(bars)
        if len(series) < 2:
            return False
        prev_k, prev_d = series[-2]
        k, d = series[-1]
        if cond["direction"] == "golden":
            return prev_k <= prev_d and k > d
        return prev_k >= prev_d and k < d

    if t == "ma_compare":
        fast_ma = latest_ma(bars, cond["fast"])
        slow_ma = latest_ma(bars, cond["slow"])
        if fast_ma is None or slow_ma is None:
            return False
        return fast_ma > slow_ma if cond["operator"] == "gt" else fast_ma < slow_ma

    if t == "price_vs_ma":
        ma = latest_ma(bars, cond["period"])
        if ma is None or not bars:
            return False
        price = bars[-1].close
        return price > ma if cond["operator"] == "gt" else price < ma

    if t == "streak":
        direction, days = streak(bars)
        return direction == cond["direction"] and days >= cond["days"]

    if t == "cumulative_change":
        pct = cumulative_change_percent(bars, cond["days"])
        if pct is None:
            return False
        return _compare(pct, cond["operator"], cond["percent"])

    return False


def evaluate_all(conditions: list[dict], bars: list[DailyBar]) -> bool:
    """所有條件都要成立（AND）。沒有任何條件的話視為不成立，避免空條件清單
    被誤判成「永遠符合」而對整個市場亂下單。"""
    if not conditions:
        return False
    return all(evaluate_condition(cond, bars) for cond in conditions)
