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
from app.services.features.universe import PRICE_JUMP_PERCENT, is_price_jump

logger = logging.getLogger(__name__)


LABEL_ABSOLUTE = "absolute"
LABEL_EXCESS = "excess"

LABEL_MODES = [LABEL_ABSOLUTE, LABEL_EXCESS]

LABEL_MODE_LABELS: dict[str, str] = {
    LABEL_ABSOLUTE: "絕對報酬（個股自己漲多少）",
    LABEL_EXCESS: "超額報酬（個股減掉大盤）",
}

# 成交時點。跟 label_mode 是兩件獨立的事：label_mode 決定要不要減掉大盤，
# execution_mode 決定量的是哪一段價格。
EXECUTION_CLOSE = "close"
EXECUTION_NEXT_OPEN = "next_open"

EXECUTION_MODES = [EXECUTION_CLOSE, EXECUTION_NEXT_OPEN]

EXECUTION_MODE_LABELS: dict[str, str] = {
    EXECUTION_CLOSE: "收盤決策、收盤成交（收盤 D → 收盤 D+n）",
    EXECUTION_NEXT_OPEN: "盤前決策、開盤成交（開盤 D+1 → 開盤 D+1+n）",
}



def attach_labels(
    rows: FeatureFrame,
    bars_by_code: dict[str, list[DailyBar]],
    n_days: int,
    threshold_percent: float,
    label_mode: str = LABEL_ABSOLUTE,
    market_levels: dict[date, float] | None = None,
    execution_mode: str = EXECUTION_CLOSE,
    delisted_codes: set[str] | None = None,
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

    execution_mode 決定量的是哪一段價格：

    - close：收盤(D) → 收盤(D+n)。搭配收盤決策、收盤成交。
    - next_open：開盤(D+1) → 開盤(D+1+n)。搭配盤前決策、開盤成交——決策在
      09:00 之前做完，成交在開盤，所以 label 的起點是隔天的開盤價而不是
      今天的收盤價。整段視窗往後挪一天，持有長度一樣是 n 個交易日。

    這兩種模式量的是不同的區間，**算出來的 Rank IC 不能互相比較**，換模式
    等於要重建基準。

    沒有 label 的列（資料尾端不足 n 根）直接排除，回傳新的 FeatureFrame。

    **下市股票例外**（delisted_codes）：它們的 K 棒不足 n 根不是因為「未來還沒
    發生」，而是公司已經不在了。整筆丟掉的話，剛好丟掉持有到下市、跌最慘的
    那批樣本。這種情況用最後一根 K 棒的收盤價結算，期間取「市場上從進場日往後
    數 n 個交易日」；那一天超出資料範圍的話，仍然當作沒有 label。

    另外會多一欄 PRICE_JUMP_COLUMN：label 視窗裡有沒有超出漲跌幅限制的跳動。
    這裡只標記、不丟——要不要丟看用途，見 drop_price_jump_rows。
    """
    n = len(rows)
    if n == 0:
        return rows

    # 每檔股票的「日期 → 第幾根K棒」索引，查未來第 n 根用
    index_by_code: dict[str, dict[date, int]] = {}
    closes_by_code: dict[str, list[float]] = {}
    opens_by_code: dict[str, list[float]] = {}
    dates_by_code: dict[str, list[date]] = {}
    # jumps_by_code[code][k]：第 0..k 根 K 棒裡有幾根是跳動。視窗內有沒有跳動
    # 就是兩個累計值相減，不用每一列重掃一次視窗
    jumps_by_code: dict[str, np.ndarray] = {}
    for code, bars in bars_by_code.items():
        index_by_code[code] = {b.trade_date: i for i, b in enumerate(bars)}
        closes_by_code[code] = [b.close for b in bars]
        opens_by_code[code] = [b.open for b in bars]
        dates_by_code[code] = [b.trade_date for b in bars]
        jumps_by_code[code] = np.cumsum(
            [False] + [is_price_jump(bars[k - 1].close, bars[k].close) for k in range(1, len(bars))]
        )

    # 兩種模式差在「從哪一根 K 棒的哪個價格進、哪一根的哪個價格出」。
    # close：  進 = 收盤(j)、出 = 收盤(j+n)
    # next_open：進 = 開盤(j+1)、出 = 開盤(j+1+n)
    entry_offset = 1 if execution_mode == EXECUTION_NEXT_OPEN else 0
    prices = opens_by_code if execution_mode == EXECUTION_NEXT_OPEN else closes_by_code

    future_return = np.full(n, np.nan, dtype=np.float64)
    jump_in_window = np.zeros(n, dtype=np.float64)
    codes = rows.stock_codes()

    # 只有真的有下市股票時才需要市場交易日曆（算「本來該出場的那一天」）
    delisted_codes = {c for c in (delisted_codes or ()) if c in bars_by_code}
    calendar: list[date] = []
    calendar_index: dict[date, int] = {}
    if delisted_codes:
        calendar = sorted({d for dates in dates_by_code.values() for d in dates})
        calendar_index = {d: i for i, d in enumerate(calendar)}
    settled = 0

    for i in range(n):
        code = codes[i]
        index_map = index_by_code.get(code)
        if index_map is None:
            continue
        today = date.fromordinal(int(rows.dates[i]))
        j = index_map.get(today)
        if j is None:
            continue
        start_index = j + entry_offset
        exit_index = start_index + n_days
        if start_index >= len(prices[code]):
            continue  # 下一根 K 棒不存在，開盤買不到
        entry = prices[code][start_index]
        entry_date = dates_by_code[code][start_index]
        if exit_index < len(prices[code]):
            exit_price = prices[code][exit_index]
            exit_date = dates_by_code[code][exit_index]
        elif code in delisted_codes:
            # 下市：最後一根 K 棒之後就沒有價格了，用最後收盤價結算
            market_exit = calendar_index[entry_date] + n_days
            if market_exit >= len(calendar):
                continue  # 本來該出場的那天超出資料範圍，跟下市無關
            exit_price = closes_by_code[code][-1]
            exit_date = calendar[market_exit]
            settled += 1
        else:
            continue
        if not entry or entry <= 0:
            continue
        value = (exit_price - entry) / entry * 100

        if label_mode == LABEL_EXCESS:
            # 大盤要比的是「這筆持有實際經過的那一段」，所以起點也跟著
            # entry_offset 移動——不然 next_open 模式會拿多一天的大盤報酬去減
            market = _market_return_between(market_levels, entry_date, exit_date)
            if market is None:
                continue
            value -= market
        future_return[i] = value
        # 看第 j+1 到 exit_index 根的收盤跳動。close 模式剛好是整個視窗；
        # next_open 模式多看了第 j+1 根收盤相對第 j 根的變動，那一段有一部分
        # （收盤 j → 開盤 j+1 的跳空）不在 label 裡——寧可多丟幾筆，也不要漏掉
        # 「開盤 j+1 當天就已經是新價格基準」的情況
        jumps = jumps_by_code[code]
        jump_in_window[i] = float(jumps[exit_index] - jumps[j] > 0)

    keep = ~np.isnan(future_return)
    labeled = rows.mask(keep)
    kept_returns = future_return[keep]
    labeled.set_column("future_return_percent", kept_returns)
    labeled.set_column("label", (kept_returns > threshold_percent).astype(np.float64))
    labeled.set_column(PRICE_JUMP_COLUMN, jump_in_window[keep])

    logger.info(
        "attach_labels(%s/%s): %d 列有完整 label（原始 %d 列）"
        "，其中 %d 列持有到下市、用最後收盤價結算，%d 列的視窗含 ±%.1f%% 以上跳動",
        label_mode,
        execution_mode,
        len(labeled),
        n,
        settled,
        int(jump_in_window[keep].sum()),
        PRICE_JUMP_PERCENT,
    )
    return labeled


PRICE_JUMP_COLUMN = "price_jump_in_window"


def drop_price_jump_rows(rows: FeatureFrame) -> FeatureFrame:
    """丟掉 label 視窗內有跳動的樣本。用在「拿 label 當答案」的地方：訓練、
    驗證、測試評分、預測散佈圖。

    **為什麼丟而不是截尾（clip / winsorize）。** 這些 label 不是「很極端但真實
    的報酬」，而是算錯的數字：日K沒有還原，減資或反分割那天價格基準直接換掉，
    00685L 反分割一天 -96%，實際持有人的報酬是 0。截到 -20% 仍然在告訴模型
    「這是一筆大虧」，方向與大小都是假的，只是錯得比較不顯眼；截尾適用於
    「值是對的、只是太大」的情況，這裡不是。丟掉的量也很小——普通股母體裡
    約 0.2% 的樣本。

    **為什麼回測選股時不丟。** 「接下來 n 天會不會除權、減資」在決策當下是
    不知道的；用它去排除候選股，等於讓回測用未來資訊避開了踩雷的那幾檔。
    所以逐日模擬（simulate_trading）拿的是沒丟過的測試列。

    **為什麼不在 attach_labels 裡直接丟。** 排名化是同一天全市場的橫斷面
    運算，先丟再排名的話，某檔股票因為「未來會減資」而從當天的名次裡消失，
    其他股票的分位數就跟著變——那也是未來資訊，而且推論時的名次是用完整
    的當日母體算的，兩邊會對不上。所以一律在橫斷面轉換做完、切分之後才丟。
    """
    if len(rows) == 0 or PRICE_JUMP_COLUMN not in rows.extras:
        return rows
    return rows.mask(rows.column(PRICE_JUMP_COLUMN) == 0)


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

