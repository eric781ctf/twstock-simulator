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
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from app.models import DailyBar

logger = logging.getLogger(__name__)


LABEL_ABSOLUTE = "absolute"
LABEL_EXCESS = "excess"

LABEL_MODES = [LABEL_ABSOLUTE, LABEL_EXCESS]

LABEL_MODE_LABELS: dict[str, str] = {
    LABEL_ABSOLUTE: "絕對報酬（個股自己漲多少）",
    LABEL_EXCESS: "超額報酬（個股減掉大盤）",
}


def attach_labels(
    rows: list[dict],
    bars_by_code: dict[str, list[DailyBar]],
    n_days: int,
    threshold_percent: float,
    label_mode: str = LABEL_ABSOLUTE,
    market_levels: dict[date, float] | None = None,
) -> list[dict]:
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

        if label_mode == LABEL_EXCESS:
            market_return = _market_return_between(
                market_levels, bars[i].trade_date, bars[i + n_days].trade_date
            )
            if market_return is None:
                continue  # 這段期間算不出大盤報酬，就沒有可信的超額報酬可以當答案
            future_return -= market_return

        row = dict(row)
        row["future_return_percent"] = future_return
        row["label"] = 1 if future_return > threshold_percent else 0
        labeled.append(row)

    logger.info(
        "attach_labels(%s): %d 列有完整 label（原始 %d 列）", label_mode, len(labeled), len(rows)
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
    """標準化。x 可以是 (N, F) 或序列模型的 (N, T, F)——最後一維都是特徵，
    numpy 的 broadcasting 會自動對到，所以兩種形狀共用同一份實作。

    mean/std 先轉成跟 x 一樣的精度，輸出才不會被無聲地升成 float64。序列資料
    動輒數百 MB，白白升一倍精度只是浪費記憶體——反正送進 torch 時還是會被
    轉回 float32。
    """
    mean = np.asarray(mean, dtype=x.dtype)
    std = np.asarray(std, dtype=x.dtype)
    filled = np.where(np.isnan(x), mean, x)
    return (filled - mean) / std


def fit_scaler_sequences(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """序列版的 fit_scaler：把 (N, T, F) 攤平成 (N×T, F) 再算。

    刻意用整個視窗而不是只用最後一天來算 mean/std——網路每個時間步看到的都是
    標準化過的值，基準當然要涵蓋所有時間步。
    """
    return fit_scaler(x.reshape(-1, x.shape[-1]))


SCALING_ZSCORE = "zscore"
SCALING_RANK = "cross_sectional_rank"

SCALING_MODES = [SCALING_ZSCORE, SCALING_RANK]

SCALING_MODE_LABELS: dict[str, str] = {
    SCALING_ZSCORE: "z-score（用整個訓練期的平均與標準差）",
    SCALING_RANK: "橫斷面排名（每天各自換算成全市場分位數）",
}


def _write_back(rows: list[dict], keys: list[str], values: pd.DataFrame) -> list[dict]:
    """把算好的欄位寫回 row dict。

    先轉成一個 numpy 陣列再逐格取，而不是對每一格呼叫 `.iat`——三十幾萬列乘上
    七十幾個特徵是兩千多萬格，`.iat` 的每格開銷在這個量級會變成幾十秒。
    """
    matrix = values[keys].to_numpy(dtype="float64", copy=False)
    nan_mask = np.isnan(matrix)
    out: list[dict] = []
    for i, row in enumerate(rows):
        new_row = dict(row)
        for j, key in enumerate(keys):
            new_row[key] = None if nan_mask[i, j] else float(matrix[i, j])
        out.append(new_row)
    return out


def rank_normalize(rows: list[dict], feature_keys: list[str], skip: set[str] | None = None) -> list[dict]:
    """把每個特徵換成「當天在全市場的分位數」（0~1）。

    這是業界處理橫斷面選股特徵的標準做法，跟現行的 z-score 差在基準：

    - z-score 用**整個訓練期**的平均與標準差，等於拿 2025 年的數值直接跟
      2026 年比。市場整體波動變大的時期，所有股票的特徵會一起偏移。
    - 排名只用**當天**的橫斷面，比的是「這檔今天在全市場排第幾」——而那正是
      選股要的。極端值自動被壓進 0~1，不用另外 winsorize。

    只用同一天的資料，不看未來，所以在切分之前做是安全的。

    缺值維持缺值：排名是相對位置，硬給一個數字等於憑空捏造一個名次。

    **skip 裡的特徵不做排名。** 大盤特徵（市場漲跌幅、市場寬度…）在同一天對
    所有股票是同一個值，做橫斷面排名會讓 1362 檔股票全部拿到同一個名次，
    等於把那個特徵徹底消滅。實測沒排除時，測試 Rank IC 從 +0.053 掉到 +0.023、
    標準差從 0.020 漲到 0.046——正是因為佔了近兩成重要性的大盤特徵整批失效。
    這類「橫斷面上是常數」的特徵本來就不該用橫斷面排名處理。
    """
    skip = skip or set()
    rank_keys = [k for k in feature_keys if k not in skip]
    if not rank_keys:
        return rows
    if not rows:
        return rows

    frame = pd.DataFrame(
        {key: [row.get(key) for row in rows] for key in rank_keys},
        dtype="float64",
    )
    frame["__day"] = [row["as_of_date"] for row in rows]

    ranked = frame.groupby("__day", sort=False)[rank_keys].rank(pct=True)
    out = _write_back(rows, rank_keys, ranked)

    logger.info(
        "rank_normalize: %d 列、%d 個特徵換算成當日橫斷面分位數（%d 個跳過）",
        len(out),
        len(rank_keys),
        len(feature_keys) - len(rank_keys),
    )
    return out


# 產業中性化的最小分組人數。低於這個數的產業當天會被併成「零星產業」一組——
# 一檔自成一組時減掉自己的中位數恆等於 0，等於把那一列的特徵全部抹掉
MIN_GROUP_SIZE = 3


def industry_neutralize(
    rows: list[dict],
    feature_keys: list[str],
    industry_map: dict[str, str],
    skip: set[str] | None = None,
) -> list[dict]:
    """把每個特徵減掉「當天、同產業」的中位數。

    「電子股今天全漲」不該被當成個股 alpha。減掉同業中位數之後，剩下的才是
    這檔相對同業的強弱——這也是多因子模型處理產業曝險的標準做法。

    用中位數而不是平均數：產業內常有一兩檔極端值（漲停、剛除權），平均數會被
    它們拉走，中位數不會。

    skip 裡的特徵不處理，理由跟 rank_normalize 一樣：大盤特徵在同一天對所有
    股票是同一個值，減掉同業中位數會讓它整欄變成 0。

    沒有產業別的證券（ETF、受益證券）自成一組。它們不該跟個股比，但彼此之間
    比是有意義的——把它們丟進「未分類」這一組，而不是留著不處理。

    **人數太少的產業會被併成同一組。** 一檔股票自己一組時，減掉自己的中位數
    恆等於 0，那個特徵就被徹底消滅了；兩檔的話也只剩下彼此的正負號。所以當天
    不到 MIN_GROUP_SIZE 檔的產業會一起丟進「零星產業」這一組——併組之後至少
    還是在跟別人比，比整欄變成 0 有意義。
    """
    if not rows:
        return rows

    skip = skip or set()
    target_keys = [k for k in feature_keys if k not in skip]
    if not target_keys:
        return rows

    frame = pd.DataFrame(
        {key: [row.get(key) for row in rows] for key in target_keys},
        dtype="float64",
    )
    raw_groups = [
        f"{row['as_of_date']}|{industry_map.get(row['stock_code'], 'UNKNOWN')}" for row in rows
    ]
    sizes = Counter(raw_groups)
    frame["__group"] = [
        g if sizes[g] >= MIN_GROUP_SIZE else f"{g.split('|', 1)[0]}|__SPARSE__" for g in raw_groups
    ]

    medians = frame.groupby("__group", sort=False)[target_keys].transform("median")
    neutral = frame[target_keys] - medians
    out = _write_back(rows, target_keys, neutral)

    logger.info(
        "industry_neutralize: %d 列、%d 個特徵減去同日同產業中位數（%d 個跳過）",
        len(out),
        len(target_keys),
        len(feature_keys) - len(target_keys),
    )
    return out
