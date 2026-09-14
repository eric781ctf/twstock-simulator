"""特徵的橫斷面轉換與標準化。

這裡的每個轉換都只用「同一天的橫斷面」，不看未來，所以在資料切分之前做是
安全的——而且必須在切分之前做：每折各自排名的話，同一天的同一檔股票會因為
落在不同折而拿到不同的名次，那是沒有意義的。
"""

import logging
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from app.models import DailyBar
from app.services.features.frame import FeatureFrame

logger = logging.getLogger(__name__)


SCALING_ZSCORE = "zscore"
SCALING_RANK = "cross_sectional_rank"

SCALING_MODES = [SCALING_ZSCORE, SCALING_RANK]

SCALING_MODE_LABELS: dict[str, str] = {
    SCALING_ZSCORE: "z-score（用整個訓練期的平均與標準差）",
    SCALING_RANK: "橫斷面排名（每天各自換算成全市場分位數）",
}


def rank_normalize(
    rows: FeatureFrame, feature_keys: list[str], skip: set[str] | None = None
) -> FeatureFrame:
    """把每個特徵換成「當天在全市場的分位數」（0~1）。

    這是業界處理橫斷面選股特徵的標準做法，跟 z-score 差在基準：z-score 用整個
    訓練期的平均與標準差，等於拿去年的數值直接跟今年比；排名只用當天的橫斷面，
    比的是「這檔今天在全市場排第幾」——而那正是選股要的。極端值自動被壓進
    0~1，不用另外 winsorize。只用同一天的資料，不看未來。

    缺值維持缺值：排名是相對位置，硬給一個數字等於憑空捏造一個名次。

    **skip 裡的特徵不做排名。** 大盤特徵在同一天對所有股票是同一個值，做橫斷面
    排名會讓全部股票拿到同一個名次，等於把那個特徵徹底消滅；產業 one-hot 是
    0/1 指示欄，同理。實測沒排除時，測試 Rank IC 從 +0.053 掉到 +0.023。

    **就地改寫矩陣。** 先前每次轉換都要重建整個 list of dict（一列複製一次），
    現在只是對幾個欄位做 groupby-rank，記憶體與時間都少一個數量級。
    """
    skip = skip or set()
    rank_keys = [k for k in feature_keys if k not in skip and k in rows.key_index]
    if not rank_keys or len(rows) == 0:
        return rows

    idx = [rows.key_index[k] for k in rank_keys]
    block = pd.DataFrame(rows.values[:, idx].astype(np.float64), columns=rank_keys)
    block["__day"] = rows.dates
    ranked = block.groupby("__day", sort=False)[rank_keys].rank(pct=True)
    rows.values[:, idx] = ranked.to_numpy(dtype=np.float64)

    logger.info(
        "rank_normalize: %d 列、%d 個特徵換算成當日橫斷面分位數（%d 個跳過）",
        len(rows),
        len(rank_keys),
        len(feature_keys) - len(rank_keys),
    )
    return rows


# 產業中性化的最小分組人數。低於這個數的產業當天會被併成「零星產業」一組——
# 一檔自成一組時減掉自己的中位數恆等於 0，等於把那一列的特徵全部抹掉

MIN_GROUP_SIZE = 3


def industry_neutralize(
    rows: FeatureFrame,
    feature_keys: list[str],
    industry_map: dict[str, str],
    skip: set[str] | None = None,
) -> FeatureFrame:
    """把每個特徵減掉「當天、同產業」的中位數。

    「電子股今天全漲」不該被當成個股 alpha。減掉同業中位數之後，剩下的才是這檔
    相對同業的強弱——這也是多因子模型處理產業曝險的標準做法。用中位數而不是
    平均數：產業內常有一兩檔極端值（漲停、剛除權），平均數會被拉走。

    skip 的理由跟 rank_normalize 一樣。沒有產業別的證券（ETF、受益證券）自成
    「未分類」一組——它們不該跟個股比，但彼此之間比是有意義的。

    不到 MIN_GROUP_SIZE 檔的產業會併成「零星產業」一組：一檔自己一組時減掉
    自己的中位數恆等於 0，那個特徵就被徹底消滅了。

    跟 rank_normalize 一樣就地改寫矩陣，不重建整張表。

    **實測是有害的**（+0.065 → +0.039，連訓練分數都一起掉），所以預設關閉。
    """
    if len(rows) == 0:
        return rows

    skip = skip or set()
    target_keys = [k for k in feature_keys if k not in skip and k in rows.key_index]
    if not target_keys:
        return rows

    idx = [rows.key_index[k] for k in target_keys]
    codes = rows.stock_codes()
    raw_groups = [
        f"{d}|{industry_map.get(c, 'UNKNOWN')}" for d, c in zip(rows.dates.tolist(), codes)
    ]
    sizes = Counter(raw_groups)
    groups = [
        g if sizes[g] >= MIN_GROUP_SIZE else f"{g.split('|', 1)[0]}|__SPARSE__"
        for g in raw_groups
    ]

    block = pd.DataFrame(rows.values[:, idx].astype(np.float64), columns=target_keys)
    block["__group"] = groups
    medians = block.groupby("__group", sort=False)[target_keys].transform("median")
    rows.values[:, idx] = (block[target_keys] - medians).to_numpy(dtype=np.float64)

    logger.info(
        "industry_neutralize: %d 列、%d 個特徵減去同日同產業中位數（%d 個跳過）",
        len(rows),
        len(target_keys),
        len(feature_keys) - len(target_keys),
    )
    return rows


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

