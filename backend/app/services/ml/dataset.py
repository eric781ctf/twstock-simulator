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
from app.services.ml.frame import FeatureFrame

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
