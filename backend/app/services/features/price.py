"""價量特徵的向量化計算。

原本的做法是「逐股票、逐日」的 Python 迴圈，每天重新切一次 list。特徵數少的
時候還可以（31 個特徵、54 萬列約 20 秒），但要加到 Alpha158 那種等級、又要算
60 天的滾動統計，同樣的寫法會變成好幾分鐘——而訓練跟每日選股都要跑一次。

這裡改成整欄一次算完。關鍵手法是**先把所有股票的資料按 (代號, 日期) 排好，
對整欄做 rolling，再把跨股票邊界的那些列遮掉**：

    2330 的第 1..4 列   ← 視窗不滿 5 天，遮掉
    2330 的第 5..N 列   ← 有效
    2317 的第 1..4 列   ← 這裡如果不遮，視窗會吃到 2330 的尾巴

遮掉的依據是「這一列在自己股票裡排第幾」。這樣一次 C 層級的掃描就能算完全部
股票，語意跟逐股票分別算完全一致——每個視窗裡的資料仍然只來自同一檔股票。

沒有做的事：KD 是遞迴平滑、且跟策略引擎共用同一份實作，留在原本的路徑；
估值、大盤、籌碼面本來就不是逐日滾動，也留在原處。
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 滾動視窗。刻意不放 30——它跟 20 與 60 的相關性太高，多算一組換不到資訊
WINDOWS = [5, 10, 20, 60]


def build_price_frame(bars_by_code: dict[str, list]) -> pd.DataFrame:
    """把日K攤平成一張長表，依 (股票代號, 日期) 排序。"""
    records = []
    for code, bars in bars_by_code.items():
        for bar in bars:
            records.append(
                (code, bar.trade_date, bar.open, bar.high, bar.low, bar.close, float(bar.volume))
            )
    frame = pd.DataFrame.from_records(
        records, columns=["stock_code", "as_of_date", "open", "high", "low", "close", "volume"]
    )
    frame.sort_values(["stock_code", "as_of_date"], inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def _position_in_group(frame: pd.DataFrame) -> np.ndarray:
    """每一列在自己那檔股票裡排第幾（從 0 起算）。用來遮掉視窗不滿的列。"""
    return frame.groupby("stock_code", sort=False).cumcount().to_numpy()


def _safe_div(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    """除法，分母為 0 或缺值時給 NaN 而不是 inf。

    inf 會一路汙染到標準化（mean/std 都變成 inf），比缺值難追蹤得多。
    """
    result = numerator / denominator.replace(0, np.nan)
    return result.replace([np.inf, -np.inf], np.nan)


def compute_price_features(frame: pd.DataFrame) -> pd.DataFrame:
    """算出所有價量衍生特徵，回傳跟輸入同樣列數的 DataFrame。"""
    out = pd.DataFrame(index=frame.index)
    position = _position_in_group(frame)
    grouped = frame.groupby("stock_code", sort=False)

    open_, high, low, close, volume = (frame[c] for c in ("open", "high", "low", "close", "volume"))
    prev_close = grouped["close"].shift(1)
    daily_return = _safe_div(close - prev_close, prev_close)

    # close 留在輸出裡，但**不是特徵**：選股要拿它當進場價、回測要拿它平倉。
    # 它之所以不該當特徵，是因為絕對價位在不同股票之間不可比——1000 元的
    # 台積電和 20 元的股票，價格高低本身跟接下來會漲會跌沒有關係。實測把它
    # 放進特徵時，樹模型會把它排到第一名（7.4%），最合理的解釋是拿它當
    # 「這是哪一檔股票」的身分證在背資料，而那只會灌高訓練分數。
    # volume 同理：單日成交股數的量級直接反映股本大小，不是可比的訊號。
    out["close"] = close
    out["volume"] = volume
    out["change_percent"] = daily_return * 100

    # ── K 棒形狀 ─────────────────────────────────────────────────────
    # 全部是比例而不是絕對價差，這樣不同價位的股票才可比
    body = close - open_
    full_range = (high - low).replace(0, np.nan)
    upper = high - np.maximum(open_, close)
    lower = np.minimum(open_, close) - low

    out["kmid"] = _safe_div(body, open_)
    out["klen"] = _safe_div(high - low, open_)
    out["kmid2"] = body / full_range
    out["kup"] = _safe_div(upper, open_)
    out["kup2"] = upper / full_range
    out["klow"] = _safe_div(lower, open_)
    out["klow2"] = lower / full_range
    out["ksft"] = _safe_div(2 * close - high - low, open_)
    out["ksft2"] = (2 * close - high - low) / full_range

    # ── 當日價格結構（除以收盤價正規化）───────────────────────────
    # open_over_close 不放：它跟 kmid 的相關係數是 -0.998（kmid = (收-開)/開，
    # 兩者其實在講同一件事），留一個就好
    out["high_over_close"] = _safe_div(high, close)
    out["low_over_close"] = _safe_div(low, close)

    # ── 滾動統計 ─────────────────────────────────────────────────────
    log_volume = np.log1p(volume)
    # 供 rolling corr 用的時間軸。視窗內一定同一檔股票（跨邊界的列會被遮掉），
    # 所以直接用全域列號當等距時間軸即可
    row_number = pd.Series(np.arange(len(frame), dtype=float), index=frame.index)

    for window in WINDOWS:
        mask = position >= window  # 視窗不滿就不給值

        def masked(series: pd.Series) -> pd.Series:
            return series.where(mask)

        # 動能：往回 window 天的報酬率
        out[f"roc_{window}"] = masked(_safe_div(close, grouped["close"].shift(window)) - 1) * 100
        # 波動：日報酬的標準差
        out[f"std_{window}"] = masked(daily_return.rolling(window).std()) * 100
        # 趨勢品質：收盤價對時間的相關係數平方，越接近 1 代表走得越「直」
        out[f"rsqr_{window}"] = masked(close.rolling(window).corr(row_number) ** 2)
        # 上漲天數佔比
        out[f"cntp_{window}"] = masked((daily_return > 0).rolling(window).mean())
        # 量能：期間均量相對今日量
        out[f"vma_{window}"] = masked(_safe_div(volume.rolling(window).mean(), volume))
        # 量價相關：價漲是否伴隨量增
        out[f"volcorr_{window}"] = masked(close.rolling(window).corr(log_volume))
        # RSV：收盤價在期間高低區間裡的位置
        highest = high.rolling(window).max()
        lowest = low.rolling(window).min()
        out[f"rsv_{window}"] = masked(_safe_div(close - lowest, highest - lowest) * 100)

    # ── 沿用原本就有的那幾個（改成向量化寫法）──────────────────────
    for period in (5, 20, 60):
        ma = close.rolling(period).mean().where(position >= period - 1)
        out[f"ma{period}_bias"] = _safe_div(close - ma, ma) * 100
        if period == 5:
            ma5 = ma
        elif period == 20:
            ma20 = ma
        else:
            ma60 = ma
    out["ma5_over_ma20"] = _safe_div(ma5, ma20)
    out["ma20_over_ma60"] = _safe_div(ma20, ma60)

    avg_volume_5 = volume.rolling(5).mean().where(position >= 4)
    out["volume_ratio_5"] = _safe_div(volume, avg_volume_5)

    # volatility_20 / cumulative_change_5 / cumulative_change_20 已經移除：
    # 它們跟 std_20 / roc_5 / roc_20 是逐點完全相同的值（實測 56,539 個點全部
    # 相符）。留著兩份不只是浪費計算——樹模型會把重要性拆散到兩個欄位上，
    # 讓「模型倚重什麼」的解讀失真；線性模型則會直接碰到完全共線。

    out["streak_days"] = _streak_days(frame, daily_return)

    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    return out


def _streak_days(frame: pd.DataFrame, daily_return: pd.Series) -> pd.Series:
    """連續上漲（正）或連續下跌（負）的天數。

    向量化的做法：把漲跌方向轉成 +1/-1/0，方向一改變就開一個新的「段」，
    再用段內累計次數當連續天數。比逐列往回數快得多，結果一樣。
    """
    direction = np.sign(daily_return.fillna(0)).astype(int)
    # 方向變了、或換了一檔股票，就是新的一段
    changed = (direction != direction.shift(1)) | (frame["stock_code"] != frame["stock_code"].shift(1))
    segment = changed.cumsum()
    length = direction.groupby(segment).cumcount() + 1
    return (length * direction).astype(float)


# 這個模組負責的特徵（其餘由 features.py 的既有路徑提供）
# 注意這裡沒有 close 與 volume——它們是輸出欄位但不是特徵，理由見上面的註解。
# 它們的「可比版本」已經在裡面了：vma_*（量能比）、high_over_close 等等。
PRICE_FEATURE_KEYS: list[str] = (
    ["change_percent"]
    + ["kmid", "klen", "kmid2", "kup", "kup2", "klow", "klow2", "ksft", "ksft2"]
    + ["high_over_close", "low_over_close"]
    + [f"{name}_{w}" for w in WINDOWS for name in ("roc", "std", "rsqr", "cntp", "vma", "volcorr", "rsv")]
    + ["ma5_bias", "ma20_bias", "ma60_bias", "ma5_over_ma20", "ma20_over_ma60"]
    + ["volume_ratio_5", "streak_days"]
)
