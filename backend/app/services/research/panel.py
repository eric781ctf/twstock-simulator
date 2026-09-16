"""研究用的價格面板：(交易日 × 股票) 的寬矩陣。

主訓練管線用的是「每檔股票、每天一列」的長表，因為特徵要逐列餵給模型。事件
研究的運算幾乎都是「同一天跨股票比」或「同一檔跨時間滾動」，寬矩陣兩個方向
都是一次向量化，比長表 groupby 快得多，也比較不容易對錯行。

這裡同時負責兩件長表管線目前沒做的清理（見 README 或 commit 說明）：

1. **只留普通股**。上市清單裡混著 240 檔 ETF，包含槓桿與反向型。VCP 與族群
   聯動是選股方法，ETF 進來只會污染基準線。
2. **標出公司行動造成的價格跳動**。日K沒有還原除權息，台股漲跌幅上限 10%，
   收盤對收盤超過 ±10.5% 的一定不是正常交易（減資、反分割、新股前五日）。
   一般現金股利跌幅在 10% 以內，從價格本身偵測不出來——這是已知限制。
"""

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DailyBar, Market, Stock

logger = logging.getLogger(__name__)

# 超過漲跌幅上限一定是公司行動，不是市場行情
CORPORATE_ACTION_THRESHOLD = 0.105
# 開盤跳空到這個幅度視為漲停鎖死，開盤買不到（跟 exit_rules 同一個門檻）
LIMIT_UP_THRESHOLD = 0.095


def is_ordinary_stock(code: str) -> bool:
    """4 碼且不是 00 開頭。00 開頭是 ETF，5／6 碼是特別股、ETF、TDR 之類。"""
    return len(code) == 4 and code.isdigit() and not code.startswith("00")


@dataclass
class PricePanel:
    dates: list[date]
    codes: list[str]
    open: np.ndarray    # (T, N)，缺值 NaN
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    # jump[t, i]：第 t 天收盤相對前一根 K 棒超過 ±10.5%
    jump: np.ndarray

    @property
    def shape(self) -> tuple[int, int]:
        return self.close.shape

    def year_of(self) -> np.ndarray:
        return np.array([d.year for d in self.dates])


def load_panel(db: Session) -> PricePanel:
    rows = db.execute(
        select(
            DailyBar.stock_code,
            DailyBar.trade_date,
            DailyBar.open,
            DailyBar.high,
            DailyBar.low,
            DailyBar.close,
            DailyBar.volume,
        )
        .join(Stock, Stock.code == DailyBar.stock_code)
        .where(Stock.market == Market.TWSE)
    ).all()
    df = pd.DataFrame(rows, columns=["code", "date", "open", "high", "low", "close", "volume"])
    total_codes = df["code"].nunique()
    df = df[df["code"].map(is_ordinary_stock)]
    logger.info("load_panel: 上市代號 %d 個，其中普通股 %d 個", total_codes, df["code"].nunique())

    wide = {
        field: df.pivot(index="date", columns="code", values=field).sort_index()
        for field in ("open", "high", "low", "close", "volume")
    }
    close = wide["close"]

    # 跟「前一根存在的 K 棒」比，而不是跟前一個交易日比——停牌的股票中間會
    # 空好幾天，拿 NaN 去比只會把真正的跳動漏掉
    previous = close.ffill().shift(1)
    change = close / previous - 1
    jump = (change.abs() > CORPORATE_ACTION_THRESHOLD).to_numpy()

    panel = PricePanel(
        dates=list(close.index),
        codes=list(close.columns),
        open=wide["open"].to_numpy(dtype=float),
        high=wide["high"].to_numpy(dtype=float),
        low=wide["low"].to_numpy(dtype=float),
        close=close.to_numpy(dtype=float),
        volume=wide["volume"].to_numpy(dtype=float),
        jump=jump,
    )
    logger.info(
        "load_panel: %d 個交易日 × %d 檔，公司行動跳動 %d 次",
        panel.shape[0], panel.shape[1], int(jump.sum()),
    )
    return panel


def rolling(values: np.ndarray, window: int, how: str, min_periods: int | None = None) -> np.ndarray:
    """沿時間軸（第 0 軸）滾動。窗口包含當天。"""
    frame = pd.DataFrame(values)
    roller = frame.rolling(window, min_periods=min_periods or window)
    return getattr(roller, how)().to_numpy()


def shift(values: np.ndarray, periods: int) -> np.ndarray:
    """沿時間軸平移。正數＝往後挪（第 t 列拿到 t−periods 的值）。"""
    out = np.full_like(values, np.nan, dtype=float)
    if periods > 0:
        out[periods:] = values[:-periods]
    elif periods < 0:
        out[:periods] = values[-periods:]
    else:
        out[:] = values
    return out


def liquidity_mask(panel: PricePanel, min_value_traded: float, window: int = 20) -> np.ndarray:
    """過去 window 天（不含當天）的平均成交值是否達標。

    流動性太差的股票，事件研究算出來的報酬大多是價差與雜訊，而且實際上
    也買不到那個價格。用「不含當天」是因為突破當天的爆量不該讓它自己過關。
    """
    value = panel.close * panel.volume
    average = shift(rolling(value, window, "mean", min_periods=window // 2), 1)
    return average >= min_value_traded


def jump_in_window(panel: PricePanel, start_offset: int, end_offset: int) -> np.ndarray:
    """[t+start_offset, t+end_offset] 之間有沒有公司行動跳動（含兩端）。"""
    jumps = panel.jump.astype(float)
    length = end_offset - start_offset + 1
    # 先算「截至 t 的 length 天內有沒有跳動」，再往回挪到正確的起點
    window_any = rolling(jumps, length, "max", min_periods=1)
    return shift(window_any, -end_offset) > 0
