"""均線、KD、連續漲跌天數等技術指標的純函式運算，只吃 DailyBar 列表（依日期
升冪排序），不碰資料庫。演算法故意跟 frontend/src/lib/ma.ts、frontend/src/lib/kd.ts
逐行對齊，確保策略引擎判斷的訊號跟使用者在圖表上看到的數字一致。"""

from app.models import DailyBar


def latest_ma(bars: list[DailyBar], period: int) -> float | None:
    """跟 computeMA 一樣：只用 close，未滿 period 天不輸出。"""
    if len(bars) < period:
        return None
    window = bars[-period:]
    return sum(b.close for b in window) / period


def compute_kd_series(bars: list[DailyBar], period: int = 9) -> list[tuple[float, float]]:
    """逐行對齊 frontend/src/lib/kd.ts 的 computeKD：RSV 用成長中的視窗（前 period-1
    天視窗不足 period 天也照算），K/D 都從 50 開始平滑。回傳每一天的 (k, d)。"""
    result: list[tuple[float, float]] = []
    prev_k = 50.0
    prev_d = 50.0
    for i in range(len(bars)):
        window = bars[max(0, i - period + 1) : i + 1]
        high = max(b.high for b in window)
        low = min(b.low for b in window)
        close = bars[i].close
        rsv = 50.0 if high == low else (close - low) / (high - low) * 100
        k = (prev_k * 2 + rsv) / 3
        d = (prev_d * 2 + k) / 3
        result.append((k, d))
        prev_k, prev_d = k, d
    return result


def latest_kd(bars: list[DailyBar], period: int = 9) -> tuple[float, float] | None:
    if not bars:
        return None
    return compute_kd_series(bars, period)[-1]


def streak(bars: list[DailyBar]) -> tuple[str, int]:
    """從最後一天往前數，收盤價連續上漲/下跌幾天。平盤（前後收盤價相同）視為
    連續中斷。回傳 ("up"|"down"|"flat", 天數)。"""
    if len(bars) < 2:
        return ("flat", 0)
    direction: str | None = None
    count = 0
    for i in range(len(bars) - 1, 0, -1):
        change = bars[i].close - bars[i - 1].close
        if change > 0:
            d = "up"
        elif change < 0:
            d = "down"
        else:
            break
        if direction is None:
            direction = d
            count = 1
        elif d == direction:
            count += 1
        else:
            break
    return (direction or "flat", count)


def cumulative_change_percent(bars: list[DailyBar], days: int) -> float | None:
    """最近 days 天的累積漲跌幅（用 days 天前的收盤價到最新收盤價）。"""
    if days < 1 or len(bars) < days + 1:
        return None
    start = bars[-(days + 1)].close
    end = bars[-1].close
    if start == 0:
        return None
    return (end - start) / start * 100


def compute_rank_value(rank_by: str, bars: list[DailyBar]) -> float | None:
    if rank_by == "change_percent":
        if len(bars) < 2 or bars[-2].close == 0:
            return None
        return (bars[-1].close - bars[-2].close) / bars[-2].close * 100
    if rank_by == "k_value":
        kd = latest_kd(bars)
        return kd[0] if kd else None
    if rank_by == "d_value":
        kd = latest_kd(bars)
        return kd[1] if kd else None
    if rank_by == "volume":
        return float(bars[-1].volume) if bars else None
    return None
