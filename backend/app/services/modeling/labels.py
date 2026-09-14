"""Label 產生、資料切分與矩陣化。

這一層回答的是「要預測什麼」與「哪些資料可以拿來訓練」，跟 features 那邊的
「特徵長什麼樣」是不同階段的問題。
"""

import logging
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from app.models import DailyBar
from app.services.features.frame import FeatureFrame

logger = logging.getLogger(__name__)


LABEL_ABSOLUTE = "absolute"
LABEL_EXCESS = "excess"

LABEL_MODES = [LABEL_ABSOLUTE, LABEL_EXCESS]

LABEL_MODE_LABELS: dict[str, str] = {
    LABEL_ABSOLUTE: "絕對報酬（個股自己漲多少）",
    LABEL_EXCESS: "超額報酬（個股減掉大盤）",
}



def attach_labels(
    rows: FeatureFrame,
    bars_by_code: dict[str, list[DailyBar]],
    n_days: int,
    threshold_percent: float,
    label_mode: str = LABEL_ABSOLUTE,
    market_levels: dict[date, float] | None = None,
) -> FeatureFrame:
    """替每一列補上未來 n 個交易日的報酬率與是否達標。

    未來價格用「同一檔股票、往後數 n 根 K 棒」的收盤價；不足 n 根（也就是資料
    尾端那幾天）就沒有 label，直接排除。

    label_mode 決定要預測哪一種報酬：

    - absolute：個股自己漲跌多少。直覺，但這個數字裡混著整個市場的方向——
      大盤漲 3% 的日子幾乎每檔都達標，跌 3% 的日子幾乎每檔都不達標，模型有
      相當一部分的容量會耗在猜大盤上。
    - excess：個股報酬減掉同一段期間的大盤報酬。把市場方向這個最大的共同
      雜訊源直接消掉，剩下的才是「這檔股票相對其他股票強不強」——而那正是
      這個系統實際在做的事（每天挑相對最強的前 10 名）。

    大盤報酬取的是「同樣的起訖日期」，不是「同樣的交易日數」：停牌過的股票
    第 n 根 K 棒可能落在比較晚的日期，這時候要比的是那段實際經過的期間。

    沒有 label 的列（資料尾端不足 n 根）直接排除，回傳新的 FeatureFrame。
    """
    n = len(rows)
    if n == 0:
        return rows

    # 每檔股票的「日期 → 第幾根K棒」索引，查未來第 n 根用
    index_by_code: dict[str, dict[date, int]] = {}
    closes_by_code: dict[str, list[float]] = {}
    dates_by_code: dict[str, list[date]] = {}
    for code, bars in bars_by_code.items():
        index_by_code[code] = {b.trade_date: i for i, b in enumerate(bars)}
        closes_by_code[code] = [b.close for b in bars]
        dates_by_code[code] = [b.trade_date for b in bars]

    future_return = np.full(n, np.nan, dtype=np.float64)
    codes = rows.stock_codes()
    close = rows.column("close")

    for i in range(n):
        code = codes[i]
        index_map = index_by_code.get(code)
        if index_map is None:
            continue
        today = date.fromordinal(int(rows.dates[i]))
        j = index_map.get(today)
        if j is None or j + n_days >= len(closes_by_code[code]):
            continue
        entry = close[i]
        if not entry or entry <= 0:
            continue
        exit_price = closes_by_code[code][j + n_days]
        value = (exit_price - entry) / entry * 100

        if label_mode == LABEL_EXCESS:
            market = _market_return_between(
                market_levels, today, dates_by_code[code][j + n_days]
            )
            if market is None:
                continue
            value -= market
        future_return[i] = value

    keep = ~np.isnan(future_return)
    labeled = rows.mask(keep)
    kept_returns = future_return[keep]
    labeled.set_column("future_return_percent", kept_returns)
    labeled.set_column("label", (kept_returns > threshold_percent).astype(np.float64))

    logger.info(
        "attach_labels(%s): %d 列有完整 label（原始 %d 列）", label_mode, len(labeled), n
    )
    return labeled


def _market_return_between(
    market_levels: dict[date, float] | None, start: date, end: date
) -> float | None:
    """大盤在 [start, end] 這段期間的報酬率。任一端沒有資料就回 None。"""
    if not market_levels:
        return None
    start_level = market_levels.get(start)
    end_level = market_levels.get(end)
    if not start_level or end_level is None:
        return None
    return (end_level - start_level) / start_level * 100



def purge_tail(rows: FeatureFrame, days: int) -> FeatureFrame:
    """丟掉這一段尾端 N 個**交易日**的樣本。

    為什麼需要：label 是「未來 n 天的報酬」，所以一筆樣本實際佔用的時間是
    [t, t+n] 而不是 t。訓練期最後 n 天的樣本，它們的答案是由驗證期的價格決定
    的——模型訓練時就看過那段漲跌，然後我們再用那段期間去評分它。

    這就是 López de Prado 說的 purging。實測我們每一折約有 4.1% 的訓練樣本
    落在這個區間裡。

    N 通常取「label 長度 + embargo」。embargo 是額外的緩衝：就算標籤不再重疊，
    緊鄰的兩段時間仍然高度相關（報酬有序列相關、特徵又是回看的滾動視窗），
    空一小段能讓評估少一點樂觀偏差。

    用交易日而不是日曆日——label 數的是 K 棒數，不是天數。
    """
    if days <= 0 or len(rows) == 0:
        return rows
    unique_days = np.unique(rows.dates)
    if len(unique_days) <= days:
        # 整段都在淨化範圍內。回空的比回原本的安全——呼叫端會當成
        # 「這一折排不下」而報錯，總比默默用一段全是洩漏的資料訓練好
        return rows.mask(np.zeros(len(rows), dtype=bool))
    cutoff = unique_days[-days]
    return rows.mask(rows.dates < cutoff)


def split_by_date(rows: FeatureFrame, start: date, end: date) -> FeatureFrame:
    return rows.between(start, end)


def to_matrix(rows: FeatureFrame, feature_keys: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把特徵表轉成 (X, y_regression, y_classification)。

    缺值留成 NaN，交給 apply_scaler 填成該欄的平均數——標準化之後平均數就是 0，
    是這裡最中性的填法。
    """
    x = rows.feature_matrix(feature_keys)
    y_reg = rows.column("future_return_percent").astype(np.float64)
    y_clf = rows.column("label").astype(np.int64)
    return x, y_reg, y_clf

