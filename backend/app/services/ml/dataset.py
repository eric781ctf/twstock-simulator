"""資料集組裝：加上雙任務 label、依時間切分成 train/validation/test、標準化。

三件事情特別重要（都是為了讓回測結果可信）：

1. **label 只看未來、特徵只看過去**：label 是「未來 n 個交易日的報酬率」，
   所以最後 n 天的特徵列沒有答案可以對，一律丟掉，不能拿沒成熟的 label 訓練。
2. **依時間切分，不隨機切分**：股票資料有時序性，隨機切分會讓模型間接看到
   未來（同一天的其他股票、或後面日期的樣本進了訓練集）。
3. **標準化只用訓練集算**：mean/std 若用全部資料算，測試集的分布資訊就洩漏
   到訓練階段了。這裡把訓練集算出來的 mean/std 存進模型檔，之後正式上線推論
   時也要用同一組數字。
"""

import logging
from datetime import date

import numpy as np

from app.models import DailyBar

logger = logging.getLogger(__name__)


def attach_labels(
    rows: list[dict],
    bars_by_code: dict[str, list[DailyBar]],
    n_days: int,
    threshold_percent: float,
) -> list[dict]:
    """替每一列補上未來 n 個交易日的報酬率與是否達標。

    未來價格用「同一檔股票、往後數 n 根 K 棒」的收盤價；不足 n 根（也就是資料
    尾端那幾天）就沒有 label，直接排除。
    """
    close_index: dict[str, dict[date, int]] = {}
    for code, bars in bars_by_code.items():
        close_index[code] = {bar.trade_date: i for i, bar in enumerate(bars)}

    labeled: list[dict] = []
    for row in rows:
        code = row["stock_code"]
        bars = bars_by_code.get(code)
        index_map = close_index.get(code)
        if not bars or not index_map:
            continue
        i = index_map.get(row["as_of_date"])
        if i is None or i + n_days >= len(bars):
            continue

        entry_close = bars[i].close
        future_close = bars[i + n_days].close
        if not entry_close:
            continue

        future_return = (future_close - entry_close) / entry_close * 100
        row = dict(row)
        row["future_return_percent"] = future_return
        row["label"] = 1 if future_return > threshold_percent else 0
        labeled.append(row)

    logger.info("attach_labels: %d 列有完整 label（原始 %d 列）", len(labeled), len(rows))
    return labeled


def split_by_date(rows: list[dict], start: date, end: date) -> list[dict]:
    return [r for r in rows if start <= r["as_of_date"] <= end]


def to_matrix(rows: list[dict], feature_keys: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """把特徵列轉成 (X, y_regression, y_classification)。

    缺值（例如剛上市沒有 MA60、或還沒有估值快照）補 0——在標準化之後，0 就是
    「該特徵的平均值」，是這裡最中性的填法。
    """
    x = np.zeros((len(rows), len(feature_keys)), dtype=np.float64)
    y_reg = np.zeros(len(rows), dtype=np.float64)
    y_clf = np.zeros(len(rows), dtype=np.int64)

    for i, row in enumerate(rows):
        for j, key in enumerate(feature_keys):
            value = row.get(key)
            x[i, j] = float(value) if value is not None and np.isfinite(float(value)) else np.nan
        y_reg[i] = row["future_return_percent"]
        y_clf[i] = row["label"]
    return x, y_reg, y_clf


def fit_scaler(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """只在訓練集上算 mean/std。整欄都是缺值時 std 會是 0，改成 1 避免除以零。"""
    mean = np.nanmean(x, axis=0)
    mean = np.where(np.isfinite(mean), mean, 0.0)
    std = np.nanstd(x, axis=0)
    std = np.where(np.isfinite(std) & (std > 1e-9), std, 1.0)
    return mean, std


def apply_scaler(x: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    filled = np.where(np.isnan(x), mean, x)
    return (filled - mean) / std
