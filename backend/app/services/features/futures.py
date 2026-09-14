"""台指期／電子期特徵：日盤的相對強弱與未平倉變化，以及夜盤的隔夜資訊。

夜盤是這個模組存在的理由。台股現貨 13:30 收盤之後到隔天 09:00 開盤之間，
美股完整跑完一個交易日——那段時間對台股的影響在現貨價格上完全看不到，
但台指期夜盤（15:00 到隔日 05:00）是即時反映的。

**日期歸屬**：期交所把「D−1 日 15:00 開始、D 日 05:00 結束」的那一節標成
日期 D（見 models.FuturesDaily 的說明與實測）。所以交易日 D 收盤之後的那一晚，
對應的是 session='night' 且 trade_date = next_trading_day(D) 的那一列。

**這造成一個刻意的不對稱**：以 D 為基準日的特徵列，隔夜欄位裝的是 D 收盤
「之後」才發生的事。這在 close 模式（收盤決策、收盤成交）下是 look-ahead，
只有在 next_open 模式（盤前決策、開盤成交，label 從開盤(D+1) 起算）下才
合法——因為那時成交點本來就在那一晚之後。所以這組欄位由 runner 硬性檢查
execution_mode，設錯直接讓訓練失敗，不靜默降級。
"""

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FuturesDaily

logger = logging.getLogger(__name__)

# 只在 execution_mode='next_open' 下合法：裝的是基準日收盤之後那一晚的事
OVERNIGHT_FEATURE_KEYS = [
    "overnight_tx_return",
    "overnight_tx_range",
    "overnight_te_return",
    "overnight_te_minus_tx",
    "overnight_tx_volume_ratio",
    "overnight_beta_return",
]

# 基準日收盤時就已知，任何模式都能用
FUTURES_FEATURE_KEYS = [
    "futures_tx_vs_market_1d",
    "futures_te_minus_tx_day",
    "futures_oi_change_5d",
]

FUTURES_FEATURE_LABELS: dict[str, str] = {
    "overnight_tx_return": "隔夜台指期漲跌幅",
    "overnight_tx_range": "隔夜台指期振幅",
    "overnight_te_return": "隔夜電子期漲跌幅",
    "overnight_te_minus_tx": "隔夜電子期相對台指期強弱",
    "overnight_tx_volume_ratio": "隔夜台指期量能倍數",
    "overnight_beta_return": "個股 beta × 隔夜台指期漲跌幅",
    "futures_tx_vs_market_1d": "台指期日盤相對等權大盤強弱",
    "futures_te_minus_tx_day": "日盤電子期相對台指期強弱",
    "futures_oi_change_5d": "台指期未平倉 5 日變化",
}

# 這些欄位在同一天對所有股票是同一個值，不能做橫斷面排名或產業中性化。
# overnight_beta_return 不在其中——它乘過個股 beta，橫斷面上有區別力
MARKET_WIDE_KEYS = frozenset(OVERNIGHT_FEATURE_KEYS + FUTURES_FEATURE_KEYS) - {
    "overnight_beta_return"
}

BETA_WINDOW = 60
_BETA_MIN_PERIODS = 30


def load_futures(db: Session, start: date, end: date) -> pd.DataFrame:
    """把 futures_daily 讀成一張 (交易日 × 契約_時段) 的寬表。"""
    rows = db.execute(
        select(
            FuturesDaily.contract,
            FuturesDaily.trade_date,
            FuturesDaily.session,
            FuturesDaily.open,
            FuturesDaily.high,
            FuturesDaily.low,
            FuturesDaily.close,
            FuturesDaily.volume,
            FuturesDaily.open_interest,
        )
        .where(FuturesDaily.trade_date >= start, FuturesDaily.trade_date <= end)
        .order_by(FuturesDaily.trade_date)
    ).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        rows,
        columns=[
            "contract", "trade_date", "session",
            "open", "high", "low", "close", "volume", "open_interest",
        ],
    )
    wide = df.pivot_table(
        index="trade_date",
        columns=["contract", "session"],
        values=["open", "high", "low", "close", "volume", "open_interest"],
        aggfunc="first",
    )
    wide.columns = [f"{field}_{contract}_{sess}".lower() for field, contract, sess in wide.columns]
    return wide.sort_index()


def build_futures_series(
    db: Session,
    start: date,
    end: date,
    market_returns: dict[date, float],
    trading_days: list[date],
) -> dict[date, dict[str, float]]:
    """算出每個交易日一組期貨特徵，回傳 {基準日 D: {欄位: 值}}。

    trading_days 必須是升冪的現貨交易日清單——隔夜欄位要用它把 D 對應到
    next_trading_day(D)，那才是 D 收盤後那一晚所屬的期交所日期。
    """
    wide = load_futures(db, start, end)
    if wide.empty:
        logger.warning("build_futures_series: %s~%s 沒有期貨資料", start, end)
        return {}

    required = ("close_tx_day", "close_tx_night", "close_te_day", "close_te_night")
    missing = [c for c in required if c not in wide.columns]
    if missing:
        logger.warning("build_futures_series: 缺少 %s，期貨特徵全部留白", missing)
        return {}

    # 夜盤量能倍數要跟「夜盤自己的」20 日均量比，不能拿日盤當基準——
    # 兩個時段的量級差一個數量級，混著比出來的倍數沒有意義
    night_volume_ma = wide["volume_tx_night"].rolling(20, min_periods=5).mean()
    has_oi = "open_interest_tx_day" in wide.columns
    oi_change_5d = wide["open_interest_tx_day"].diff(5) if has_oi else None
    oi_base = (
        wide["open_interest_tx_day"].rolling(20, min_periods=5).mean() if has_oi else None
    )

    next_day = {d: trading_days[i + 1] for i, d in enumerate(trading_days[:-1])}

    out: dict[date, dict[str, float]] = {}
    for day in trading_days:
        if day not in wide.index:
            continue
        row = wide.loc[day]
        tx_day_close = _num(row.get("close_tx_day"))
        te_day_close = _num(row.get("close_te_day"))
        if tx_day_close is None or tx_day_close <= 0:
            continue

        values: dict[str, float] = {}

        # ── 基準日收盤時就已知的部分 ────────────────────────────────
        prev = _prev_row(wide, day)
        if prev is not None:
            prev_tx = _num(prev.get("close_tx_day"))
            if prev_tx:
                tx_day_ret = (tx_day_close - prev_tx) / prev_tx * 100

                # 原本想放的是期現基差（期貨點數減現貨指數），但這個系統刻意
                # 不抓 TAIEX——build_market_series 合成的是一條從 100 起算的
                # 等權指數，拿它去減兩萬多點的期貨只會得到一個沒有意義的大數。
                #
                # 退而求其次量「台指期跑贏等權大盤多少」。台指期追的是市值加權
                # 的 TAIEX，所以這個差額裡同時混著基差變化與大小型股的強弱，
                # 不是純粹的基差——但它是手上資料能誠實算出來的東西。
                market_ret = market_returns.get(day)
                if market_ret is not None:
                    values["futures_tx_vs_market_1d"] = tx_day_ret - market_ret

                prev_te = _num(prev.get("close_te_day"))
                if prev_te and te_day_close:
                    te_day_ret = (te_day_close - prev_te) / prev_te * 100
                    values["futures_te_minus_tx_day"] = te_day_ret - tx_day_ret

        if oi_change_5d is not None:
            oi = _num(oi_change_5d.get(day))
            base = _num(oi_base.get(day)) if oi_base is not None else None
            if oi is not None and base:
                # 除以 20 日平均未平倉量。原始口數在 2020 年跟現在差一大截，
                # 而且量級（幾萬）跟其他百分比欄位差三個數量級——樹模型無所謂，
                # 線性模型跟神經網路會被它主導
                values["futures_oi_change_5d"] = oi / base * 100

        # ── D 收盤之後那一晚（期交所標成 next_trading_day(D)）──────────
        nxt = next_day.get(day)
        if nxt is not None and nxt in wide.index:
            night = wide.loc[nxt]
            tx_night_close = _num(night.get("close_tx_night"))
            if tx_night_close is not None:
                tx_night_ret = (tx_night_close - tx_day_close) / tx_day_close * 100
                values["overnight_tx_return"] = tx_night_ret

                high = _num(night.get("high_tx_night"))
                low = _num(night.get("low_tx_night"))
                if high is not None and low is not None:
                    values["overnight_tx_range"] = (high - low) / tx_day_close * 100

                te_night_close = _num(night.get("close_te_night"))
                if te_night_close is not None and te_day_close:
                    te_night_ret = (te_night_close - te_day_close) / te_day_close * 100
                    values["overnight_te_return"] = te_night_ret
                    values["overnight_te_minus_tx"] = te_night_ret - tx_night_ret

                ma = _num(night_volume_ma.get(nxt))
                vol = _num(night.get("volume_tx_night"))
                if ma and ma > 0 and vol is not None:
                    values["overnight_tx_volume_ratio"] = vol / ma

        out[day] = values

    logger.info("build_futures_series: %s~%s 產出 %d 個交易日的期貨特徵", start, end, len(out))
    return out


def _num(value) -> float | None:
    """把 pandas 取出來的值轉成有限的 Python float，缺值/inf 一律回 None。"""
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _prev_row(wide: pd.DataFrame, day: date):
    """wide 裡嚴格早於 day 的最後一列。"""
    pos = wide.index.searchsorted(day)
    if pos == 0:
        return None
    return wide.iloc[pos - 1]


def rolling_beta(frame: pd.DataFrame, market_returns: dict[date, float]) -> pd.Series:
    """每檔股票對大盤的 60 日 beta，逐列對齊 frame（暖身不足的列留 NaN）。

    beta 本身不是隔夜特徵，但 overnight_beta_return 要用它：隔夜台指期漲跌幅
    對全市場是同一個數字，橫斷面上沒有區別力；乘上個股 beta 之後才變成
    「這一晚的方向，對這檔股票預期影響多大」——高 beta 的股票在利多的夜晚
    期望漲更多，利空的夜晚期望跌更多。

    frame 必須已經依 (stock_code, as_of_date) 排序，跟 build_price_frame 一樣。
    """
    stock_ret = frame.groupby("stock_code", sort=False)["close"].pct_change() * 100
    market = frame["as_of_date"].map(market_returns).astype(float)

    work = pd.DataFrame(
        {
            "stock_code": frame["stock_code"].to_numpy(),
            "s": stock_ret.to_numpy(),
            "m": market.to_numpy(),
        }
    )
    work["sm"] = work["s"] * work["m"]
    work["mm"] = work["m"] * work["m"]

    # rolling cov/var 展開成 E[sm]−E[s]E[m] 與 E[m²]−E[m]²，四個 rolling mean
    # 就能整欄一次算完；逐股票跑 rolling.cov 在一千多檔上會慢一個數量級
    grouped = work.groupby("stock_code", sort=False)
    kw = dict(window=BETA_WINDOW, min_periods=_BETA_MIN_PERIODS)
    means = {c: grouped[c].transform(lambda x: x.rolling(**kw).mean()) for c in ("s", "m", "sm", "mm")}

    cov = means["sm"] - means["s"] * means["m"]
    var = means["mm"] - means["m"] * means["m"]
    beta = cov / var.replace(0, np.nan)
    return beta.replace([np.inf, -np.inf], np.nan)
