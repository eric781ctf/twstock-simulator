"""特徵工程：把本地的日K與估值快照組成「每檔股票、每個交易日一列」的特徵表。

只做 TWSE 上市股票。所有特徵都嚴格只用「該交易日收盤後就已經知道」的資料——
技術指標算到當天為止（不含未來），估值快照只取「日期 <= 當天」的最新一筆。
這是避免 look-ahead bias 最關鍵的一環：只要有一個特徵偷看到未來，整個回測
結果就會好看到不真實，但實際上線完全不能用。

技術指標一律呼叫 services/indicators.py 的既有純函式，跟策略引擎、前端圖表
用的是同一套演算法，不另外實作一份。
"""

import logging
from collections import defaultdict
from datetime import date

from sqlalchemy.orm import Session

from app.models import DailyBar, Market, Stock, StockValuationHistory
from app.services.indicators import compute_kd_series, cumulative_change_percent, latest_ma, streak

logger = logging.getLogger(__name__)

# 每個特徵的 key 就是給前端勾選用的識別字串
FEATURE_KEYS = [
    "close",
    "volume",
    "volume_ratio_5",
    "change_percent",
    "ma5_bias",
    "ma20_bias",
    "ma60_bias",
    "ma5_over_ma20",
    "ma20_over_ma60",
    "k_value",
    "d_value",
    "k_minus_d",
    "streak_days",
    "cumulative_change_5",
    "cumulative_change_20",
    "volatility_20",
    "pe_ratio",
    "dividend_yield",
    "pb_ratio",
]

FEATURE_LABELS: dict[str, str] = {
    "close": "收盤價",
    "volume": "成交量",
    "volume_ratio_5": "量能比（今日量 / 5日均量）",
    "change_percent": "當日漲跌幅",
    "ma5_bias": "5日均線乖離率",
    "ma20_bias": "20日均線乖離率",
    "ma60_bias": "60日均線乖離率",
    "ma5_over_ma20": "5日均線 / 20日均線",
    "ma20_over_ma60": "20日均線 / 60日均線",
    "k_value": "KD 的 K 值",
    "d_value": "KD 的 D 值",
    "k_minus_d": "K 減 D",
    "streak_days": "連續漲跌天數（漲為正、跌為負）",
    "cumulative_change_5": "近 5 日累積漲跌幅",
    "cumulative_change_20": "近 20 日累積漲跌幅",
    "volatility_20": "近 20 日報酬率標準差",
    "pe_ratio": "本益比",
    "dividend_yield": "殖利率",
    "pb_ratio": "股價淨值比",
}

DEFAULT_FEATURES = [
    "change_percent",
    "volume_ratio_5",
    "ma5_bias",
    "ma20_bias",
    "ma5_over_ma20",
    "k_value",
    "d_value",
    "k_minus_d",
    "cumulative_change_5",
    "volatility_20",
    "pe_ratio",
    "pb_ratio",
]

# 指標要算得準（尤其 MA60）需要的暖身天數；資料不足這個長度的股票不會產生特徵列
WARMUP_BARS = 60
MIN_BARS_FOR_FEATURES = 25  # 低於這個長度連 MA20/KD 都不穩，整檔跳過


def load_twse_bars(db: Session, start: date, end: date) -> dict[str, list[DailyBar]]:
    """撈出 TWSE 上市股票在 [start, end] 之間的日K，依股票代碼分組、日期升冪。"""
    rows = (
        db.query(DailyBar)
        .join(Stock, Stock.code == DailyBar.stock_code)
        .filter(Stock.market == Market.TWSE, DailyBar.trade_date >= start, DailyBar.trade_date <= end)
        .order_by(DailyBar.stock_code.asc(), DailyBar.trade_date.asc())
        .all()
    )
    bars_by_code: dict[str, list[DailyBar]] = defaultdict(list)
    for row in rows:
        bars_by_code[row.stock_code].append(row)
    return dict(bars_by_code)


def load_valuations(db: Session, start: date, end: date) -> dict[str, list[tuple[date, float | None, float | None, float | None]]]:
    """估值快照（本益比/殖利率/淨值比），依股票代碼分組、日期升冪。

    這是月頻（TWSE 回補）或逐日累積的稀疏資料，所以取用時要往前找「最後一筆
    日期 <= 特徵日」的快照（見 _valuation_as_of），不能直接對齊當天。
    """
    rows = (
        db.query(
            StockValuationHistory.stock_code,
            StockValuationHistory.as_of_date,
            StockValuationHistory.pe_ratio,
            StockValuationHistory.dividend_yield,
            StockValuationHistory.pb_ratio,
        )
        .filter(StockValuationHistory.as_of_date >= start, StockValuationHistory.as_of_date <= end)
        .order_by(StockValuationHistory.stock_code.asc(), StockValuationHistory.as_of_date.asc())
        .all()
    )
    by_code: dict[str, list[tuple]] = defaultdict(list)
    for code, as_of, pe, dy, pb in rows:
        by_code[code].append((as_of, pe, dy, pb))
    return dict(by_code)


def _valuation_as_of(snapshots: list[tuple], target: date, cursor: int) -> tuple[dict, int]:
    """從已排序的快照往前推進，回傳「日期 <= target 的最後一筆」。cursor 是上一次
    停下來的位置，因為呼叫端是依日期遞增逐日跑，這樣整段只會掃過一次。"""
    while cursor + 1 < len(snapshots) and snapshots[cursor + 1][0] <= target:
        cursor += 1
    if cursor < len(snapshots) and snapshots[cursor][0] <= target:
        _, pe, dy, pb = snapshots[cursor]
        return {"pe_ratio": pe, "dividend_yield": dy, "pb_ratio": pb}, cursor
    return {"pe_ratio": None, "dividend_yield": None, "pb_ratio": None}, cursor


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def compute_feature_row(bars: list[DailyBar], kd_series: list[tuple[float, float]], index: int) -> dict:
    """算出 bars[index] 這一天的特徵。bars 必須是日期升冪，且 index 之後的資料
    完全不會被讀到——這是「不看未來」的關鍵，所以視窗一律用 bars[: index + 1]。"""
    window = bars[: index + 1]
    today = window[-1]

    ma5 = latest_ma(window, 5)
    ma20 = latest_ma(window, 20)
    ma60 = latest_ma(window, 60)
    k, d = kd_series[index]

    prev_close = window[-2].close if len(window) >= 2 else None
    change_percent = None
    if prev_close:
        change_percent = (today.close - prev_close) / prev_close * 100

    recent_volumes = [b.volume for b in window[-5:]]
    avg_volume_5 = sum(recent_volumes) / len(recent_volumes) if recent_volumes else None

    # 近 20 日日報酬率的標準差（母體標準差，樣本數固定所以不做修正）
    volatility_20 = None
    if len(window) >= 21:
        returns = []
        for i in range(len(window) - 20, len(window)):
            prev = window[i - 1].close
            if prev:
                returns.append((window[i].close - prev) / prev)
        if returns:
            mean = sum(returns) / len(returns)
            volatility_20 = (sum((r - mean) ** 2 for r in returns) / len(returns)) ** 0.5 * 100

    direction, days = streak(window)
    streak_days = days if direction == "up" else (-days if direction == "down" else 0)

    return {
        "close": today.close,
        "volume": float(today.volume),
        "volume_ratio_5": _safe_div(float(today.volume), avg_volume_5),
        "change_percent": change_percent,
        "ma5_bias": (today.close - ma5) / ma5 * 100 if ma5 else None,
        "ma20_bias": (today.close - ma20) / ma20 * 100 if ma20 else None,
        "ma60_bias": (today.close - ma60) / ma60 * 100 if ma60 else None,
        "ma5_over_ma20": _safe_div(ma5, ma20),
        "ma20_over_ma60": _safe_div(ma20, ma60),
        "k_value": k,
        "d_value": d,
        "k_minus_d": k - d,
        "streak_days": float(streak_days),
        "cumulative_change_5": cumulative_change_percent(window, 5),
        "cumulative_change_20": cumulative_change_percent(window, 20),
        "volatility_20": volatility_20,
    }


def build_feature_rows(
    db: Session,
    fetch_start: date,
    fetch_end: date,
    feature_start: date,
) -> tuple[list[dict], dict[str, list[DailyBar]]]:
    """組出 [feature_start, fetch_end] 之間所有 TWSE 股票的特徵列。

    fetch_start 要比 feature_start 早一段（暖身期），指標才算得出來；早於
    feature_start 的日子只用來暖身，不會產出特徵列。

    回傳 (特徵列, 原始日K)。每一列是 {stock_code, as_of_date, close, <各項特徵>...}，
    還沒有 label——label 需要「未來」的價格，交給 dataset.attach_labels 用同一份
    日K去算，職責才不會跟「只能看過去」的特徵混在一起。
    """
    bars_by_code = load_twse_bars(db, fetch_start, fetch_end)
    valuations_by_code = load_valuations(db, fetch_start, fetch_end)

    rows: list[dict] = []
    for code, bars in bars_by_code.items():
        if len(bars) < MIN_BARS_FOR_FEATURES:
            continue

        kd_series = compute_kd_series(bars)
        snapshots = valuations_by_code.get(code, [])
        cursor = 0

        for index, bar in enumerate(bars):
            if bar.trade_date < feature_start:
                continue
            if index + 1 < MIN_BARS_FOR_FEATURES:
                continue  # 這一天之前的資料還不夠算指標

            valuation, cursor = _valuation_as_of(snapshots, bar.trade_date, cursor)
            row = {"stock_code": code, "as_of_date": bar.trade_date}
            row.update(compute_feature_row(bars, kd_series, index))
            row.update(valuation)
            rows.append(row)

    logger.info(
        "build_feature_rows: %s~%s 產出 %d 列特徵（涵蓋 %d 檔股票）",
        feature_start,
        fetch_end,
        len(rows),
        len(bars_by_code),
    )
    return rows, bars_by_code
