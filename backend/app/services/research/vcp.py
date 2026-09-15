"""VCP（Volatility Contraction Pattern）收斂突破的偵測。

出處是 Mark Minervini《Trade Like a Stock Market Wizard》（2013）。原書的判斷
很多是看圖的主觀判斷，這裡把它拆成可以逐日計算的條件。**所有門檻都照書上的
數字設定，事前固定、不調參**——事件研究一旦開始為了讓結果好看去調門檻，
得到的就只是對這段歷史的配適。

拆成四個可以分開檢驗的部件，這樣才看得出來「有效的到底是哪一塊」：

1. 趨勢模板（trend template）：股票處在長期上升趨勢
2. 波動收斂（contraction）：整理期間每一段的回檔越來越淺
3. 量縮（volume dry-up）：整理後段的成交量比前段少
4. 突破（breakout）：收盤突破整理區高點，而且帶量

所有條件都只用當天收盤（含）以前的資料。
"""

import numpy as np

from app.services.research.panel import PricePanel, rolling, shift

# ── 趨勢模板（書上的 8 項）──────────────────────────────────────────
MA_SHORT, MA_MID, MA_LONG = 50, 150, 200
MA_LONG_RISING_LOOKBACK = 22        # MA200 至少上升一個月
YEAR = 250
ABOVE_52W_LOW = 1.30                # 至少比 52 週低點高 30%
WITHIN_52W_HIGH = 0.75              # 距 52 週高點 25% 以內
RS_PERCENTILE = 0.70                # 相對強度排名前 30%

# ── 整理與突破 ────────────────────────────────────────────────────
BASE_SEGMENTS = 3                   # 整理期切成三段，要求回檔逐段變淺
SEGMENT_DAYS = 20
MAX_FIRST_DEPTH = 0.35              # 第一段回檔不超過 35%（太深就不是整理了）
MAX_LAST_DEPTH = 0.10               # 最後一段收斂到 10% 以內
BREAKOUT_VOLUME_MULTIPLE = 1.5      # 突破當天量至少是 50 日均量的 1.5 倍
BREAKOUT_VOLUME_WINDOW = 50


def relative_strength(panel: PricePanel) -> np.ndarray:
    """IBD 式相對強度的近似：最近一季權重加倍的 12 個月報酬，再做當天的百分位排名。

    IBD 的 RS Rating 公式沒有公開，這是開源實作裡最常見的近似版本，
    不是原版。用百分位是因為書上的門檻本來就是「排名前 30%」。
    """
    close = panel.close
    score = np.zeros_like(close)
    for lag, weight in ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2)):
        score = score + weight * (close / shift(close, lag) - 1)
    ranks = np.full_like(close, np.nan)
    for t in range(close.shape[0]):
        row = score[t]
        valid = np.isfinite(row)
        if valid.sum() < 50:
            continue
        order = row[valid].argsort().argsort()
        ranks[t, valid] = order / (valid.sum() - 1)
    return ranks


def trend_template(panel: PricePanel) -> np.ndarray:
    """書上的 8 項條件全部成立。"""
    structure, strength = trend_template_parts(panel)
    return structure & strength


def trend_template_parts(panel: PricePanel) -> tuple[np.ndarray, np.ndarray]:
    """拆成兩半：(前 7 項＝均線與 52 週位置的結構, 第 8 項＝相對強度)。

    事件研究裡趨勢模板是唯一明顯有效的部件，拆開才看得出來效果是來自
    「股價結構」還是單純的「過去一年漲得多」——後者就是學術上的動能因子，
    不需要 Minervini 也早就知道了。"""
    close = panel.close
    ma50 = rolling(close, MA_SHORT, "mean")
    ma150 = rolling(close, MA_MID, "mean")
    ma200 = rolling(close, MA_LONG, "mean")
    low52 = rolling(panel.low, YEAR, "min")
    high52 = rolling(panel.high, YEAR, "max")
    rs = relative_strength(panel)

    with np.errstate(invalid="ignore"):
        conditions = [
            (close > ma150) & (close > ma200),
            ma150 > ma200,
            ma200 > shift(ma200, MA_LONG_RISING_LOOKBACK),
            (ma50 > ma150) & (ma50 > ma200),
            close > ma50,
            close >= ABOVE_52W_LOW * low52,
            close >= WITHIN_52W_HIGH * high52,
            rs >= RS_PERCENTILE,
        ]
    structure = np.ones_like(close, dtype=bool)
    for condition in conditions[:-1]:
        structure &= condition
    return structure, conditions[-1]


def _segment_depth(panel: PricePanel, end_offset: int) -> np.ndarray:
    """[t−end_offset−SEGMENT_DAYS+1, t−end_offset] 這一段的回檔深度（高點到低點）。"""
    high = shift(rolling(panel.high, SEGMENT_DAYS, "max"), end_offset)
    low = shift(rolling(panel.low, SEGMENT_DAYS, "min"), end_offset)
    return (high - low) / high


def contraction(panel: PricePanel) -> np.ndarray:
    """突破前 60 天切成三段，回檔深度逐段變淺，而且收斂到夠窄。

    書上的收斂段不是固定長度，是看圖找出一個個回檔。固定三段各 20 天是粗糙
    的近似，但它透明、可重現，而且不需要一個會自己做判斷的 zigzag 演算法——
    那種演算法的參數本身就是另一層可以被調出好結果的自由度。

    段落不含當天（t−1 往回算），因為當天是突破日，不屬於整理期。
    """
    depths = [
        _segment_depth(panel, 1 + (BASE_SEGMENTS - 1 - k) * SEGMENT_DAYS)
        for k in range(BASE_SEGMENTS)
    ]
    with np.errstate(invalid="ignore"):
        shrinking = np.ones_like(panel.close, dtype=bool)
        for earlier, later in zip(depths, depths[1:]):
            shrinking &= later < earlier
        return shrinking & (depths[0] <= MAX_FIRST_DEPTH) & (depths[-1] <= MAX_LAST_DEPTH)


def volume_dryup(panel: PricePanel) -> np.ndarray:
    """整理最後一段的平均量，低於第一段。"""
    last = shift(rolling(panel.volume, SEGMENT_DAYS, "mean"), 1)
    first = shift(rolling(panel.volume, SEGMENT_DAYS, "mean"), 1 + (BASE_SEGMENTS - 1) * SEGMENT_DAYS)
    with np.errstate(invalid="ignore"):
        return last < first


def breakout(panel: PricePanel) -> np.ndarray:
    """收盤突破前 20 天最高價（最後一段整理的頂部＝書上的 pivot），而且帶量。"""
    pivot = shift(rolling(panel.high, SEGMENT_DAYS, "max"), 1)
    average_volume = shift(rolling(panel.volume, BREAKOUT_VOLUME_WINDOW, "mean"), 1)
    with np.errstate(invalid="ignore"):
        return (panel.close > pivot) & (panel.volume >= BREAKOUT_VOLUME_MULTIPLE * average_volume)


def first_occurrence(mask: np.ndarray, cooldown: int) -> np.ndarray:
    """同一檔股票在 cooldown 天內只算第一次。

    突破常常連續好幾天都成立（第一天突破、第二天又創新高）。全部算進去的話，
    同一次行情會被重複計數好幾次，樣本數虛胖、t 值跟著虛胖。
    """
    previous = rolling(mask.astype(float), cooldown, "max", min_periods=1)
    previous = shift(previous, 1)
    return mask & ~(previous > 0)
