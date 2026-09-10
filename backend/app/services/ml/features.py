"""特徵工程：把本地的日K與估值快照組成「每檔股票、每個交易日一列」的特徵表。

只做 TWSE 上市股票。所有特徵都嚴格只用「該交易日收盤後就已經知道」的資料——
技術指標算到當天為止（不含未來），估值快照只取「日期 <= 當天」的最新一筆。
這是避免 look-ahead bias 最關鍵的一環：只要有一個特徵偷看到未來，整個回測
結果就會好看到不真實，但實際上線完全不能用。

技術指標一律呼叫 services/indicators.py 的既有純函式，跟策略引擎、前端圖表
用的是同一套演算法，不另外實作一份。
"""

import logging
from collections import defaultdict
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from app.models import ChipDaily, DailyBar, Market, Stock, StockValuationHistory
from app.services.indicators import compute_kd_series
from app.services.ml.price_features import (
    PRICE_FEATURE_KEYS,
    WINDOWS,
    build_price_frame,
    compute_price_features,
)

logger = logging.getLogger(__name__)

# 每個特徵的 key 就是給前端勾選用的識別字串
# 完整的特徵清單由各來源拼起來，不手寫第二份——手寫的那份遲早會跟實際
# 算出來的欄位對不上，而那種不一致只會在訓練炸掉時才被發現。
_KD_FEATURE_KEYS = ["k_value", "d_value", "k_minus_d"]
_VALUATION_FEATURE_KEYS = ["pe_ratio", "dividend_yield", "pb_ratio"]

# 大盤（全市場）特徵：讓模型看得到「今天整個市場是什麼狀況」。少了這些，
# 「這檔今天漲 3%」在大盤漲 2% 和跌 2% 的日子對模型是同一件事。
MARKET_FEATURE_KEYS = [
    "market_return_1d",
    "market_return_5d",
    "market_return_20d",
    "market_breadth",
    "market_ma20_bias",
]

# 個股相對大盤的強弱——把市場方向這個最大的共同雜訊源減掉之後剩下的部分
_RELATIVE_FEATURE_KEYS = ["relative_return_1d", "relative_return_20d"]

# 籌碼面：誰在買、誰在賣。一律除以成交量做正規化——原始股數在台積電和小型股
# 之間差好幾個數量級，不除的話模型學到的會是「這是不是大型股」。
CHIP_FEATURE_KEYS = [
    "foreign_net_ratio",
    "foreign_net_ratio_5d",
    "trust_net_ratio",
    "institution_net_ratio",
    "margin_change_5d",
]

FEATURE_KEYS = (
    PRICE_FEATURE_KEYS
    + _KD_FEATURE_KEYS
    + _VALUATION_FEATURE_KEYS
    + MARKET_FEATURE_KEYS
    + _RELATIVE_FEATURE_KEYS
    + CHIP_FEATURE_KEYS
)

# 滾動類特徵是「運算子 × 視窗」的組合，標籤跟著組出來就好——手寫 28 個
# 只會有錯字，而且加一個視窗就要補一整排
_ROLLING_LABELS: dict[str, str] = {
    "roc": "近 {w} 日報酬率",
    "std": "近 {w} 日報酬標準差",
    "rsqr": "近 {w} 日趨勢直度（R²）",
    "cntp": "近 {w} 日上漲天數佔比",
    "vma": "近 {w} 日均量 / 今日量",
    "volcorr": "近 {w} 日量價相關係數",
    "rsv": "收盤價在近 {w} 日高低區間的位置",
}

FEATURE_LABELS: dict[str, str] = {
    "change_percent": "當日漲跌幅",
    # K 棒形狀：全部是比例，不同價位的股票才可比
    "kmid": "K棒 實體 / 開盤價",
    "klen": "K棒 全幅 / 開盤價",
    "kmid2": "K棒 實體 / 全幅",
    "kup": "K棒 上影線 / 開盤價",
    "kup2": "K棒 上影線 / 全幅",
    "klow": "K棒 下影線 / 開盤價",
    "klow2": "K棒 下影線 / 全幅",
    "ksft": "K棒 收盤偏移 / 開盤價",
    "ksft2": "K棒 收盤偏移 / 全幅",
    "high_over_close": "最高價 / 收盤價",
    "low_over_close": "最低價 / 收盤價",
    "ma5_bias": "5日均線乖離率",
    "ma20_bias": "20日均線乖離率",
    "ma60_bias": "60日均線乖離率",
    "ma5_over_ma20": "5日均線 / 20日均線",
    "ma20_over_ma60": "20日均線 / 60日均線",
    "volume_ratio_5": "量能比（今日量 / 5日均量）",
    "streak_days": "連續漲跌天數（漲為正、跌為負）",
    "k_value": "KD 的 K 值",
    "d_value": "KD 的 D 值",
    "k_minus_d": "K 減 D",
    "pe_ratio": "本益比",
    "dividend_yield": "殖利率",
    "pb_ratio": "股價淨值比",
    "market_return_1d": "大盤當日漲跌幅",
    "market_return_5d": "大盤近 5 日漲跌幅",
    "market_return_20d": "大盤近 20 日漲跌幅",
    "market_breadth": "市場寬度（當日上漲家數佔比 %）",
    "market_ma20_bias": "大盤 20 日均線乖離率",
    "relative_return_1d": "相對大盤強弱（當日）",
    "relative_return_20d": "相對大盤強弱（近 20 日）",
    "foreign_net_ratio": "外資買賣超 / 成交量",
    "foreign_net_ratio_5d": "外資近 5 日買賣超 / 近 5 日成交量",
    "trust_net_ratio": "投信買賣超 / 成交量",
    "institution_net_ratio": "三大法人買賣超 / 成交量",
    "margin_change_5d": "融資餘額近 5 日變化率",
}

for _window in WINDOWS:
    for _name, _template in _ROLLING_LABELS.items():
        FEATURE_LABELS[f"{_name}_{_window}"] = _template.format(w=_window)

# 清單與標籤必須完全對得上。對不上要在載入時就炸掉，不要等到訓練跑一半、
# 或前端顯示出一個 key 當標籤才發現
_missing = [key for key in FEATURE_KEYS if key not in FEATURE_LABELS]
if _missing:
    raise RuntimeError(f"這些特徵沒有中文標籤：{_missing}")

# ── 特徵集預設 ────────────────────────────────────────────────────────
# 71 個勾選框沒辦法用，所以提供幾組現成的。定義放後端一份，前端只負責顯示——
# 前端自己維護一份清單的話，加了新特徵那邊不會自己跟上。

# 精選：人工挑過、彼此重疊較少的一組。相對強弱與籌碼面預設就在裡面，
# 因為它們是這個系統最可能帶來訊號的部分
CURATED_FEATURES = [
    "change_percent",
    "volume_ratio_5",
    "ma5_bias",
    "ma20_bias",
    "ma5_over_ma20",
    "k_value",
    "d_value",
    "k_minus_d",
    "roc_5",
    "std_20",
    "pe_ratio",
    "pb_ratio",
    "market_return_1d",
    "market_breadth",
    "relative_return_1d",
    "relative_return_20d",
    "foreign_net_ratio",
    "foreign_net_ratio_5d",
    "institution_net_ratio",
]

# 純價量：不含估值與籌碼面，用來對照「基本面與籌碼面到底有沒有加分」
PRICE_ONLY_FEATURES = list(PRICE_FEATURE_KEYS) + _KD_FEATURE_KEYS

DEFAULT_FEATURES = CURATED_FEATURES

FEATURE_PRESETS: list[dict] = [
    {
        "key": "curated",
        "label": "精選",
        "description": f"人工挑過、彼此重疊較少的 {len(CURATED_FEATURES)} 項，含相對強弱與籌碼面。",
        "features": CURATED_FEATURES,
    },
    {
        "key": "alpha_lite",
        "label": "Alpha158 精簡版",
        "description": (
            f"全部 {len(FEATURE_KEYS)} 項，做法參考 Qlib 的 Alpha158（K棒形狀 + 多視窗滾動統計），"
            "但只取其中相關性較低的一部分。特徵多不等於比較好——樣本數沒變的情況下，"
            "更容易過擬合，樹模型還撐得住，線性模型會明顯受害。"
        ),
        "features": list(FEATURE_KEYS),
    },
    {
        "key": "price_only",
        "label": "純價量",
        "description": f"只用價量與技術指標的 {len(PRICE_ONLY_FEATURES)} 項，不含估值、大盤與籌碼面。適合當對照組。",
        "features": PRICE_ONLY_FEATURES,
    },
]

# 指標要算得準（尤其 MA60）需要的暖身天數；資料不足這個長度的股票不會產生特徵列
WARMUP_BARS = 60
MIN_BARS_FOR_FEATURES = 25  # 低於這個長度連 MA20/KD 都不穩，整檔跳過


def load_twse_bars(db: Session, start: date, end: date) -> dict[str, list[DailyBar]]:
    """撈出 TWSE 上市股票在 [start, end] 之間的日K，依股票代碼分組、日期升冪。"""
    rows = (
        db.query(DailyBar)
        .join(Stock, Stock.code == DailyBar.stock_code)
        .filter(Stock.market == Market.TWSE, DailyBar.trade_date >= start, DailyBar.trade_date <= end)
        .order_by(DailyBar.stock_code.asc(), DailyBar.trade_date.asc())
        .all()
    )
    bars_by_code: dict[str, list[DailyBar]] = defaultdict(list)
    for row in rows:
        bars_by_code[row.stock_code].append(row)
    return dict(bars_by_code)







def build_market_series(bars_by_code: dict[str, list[DailyBar]]) -> dict[date, dict]:
    """從全市場的日K算出每個交易日的大盤狀態。

    刻意**不**去抓大盤指數（TAIEX）：那要多一個外部資料來源、多一條回補管線，
    而我們手上本來就有全市場每一檔的日K，等權平均出來的市場報酬已經是很好的
    代理，而且跟個股特徵完全同源、同一天一定都有資料。

    等權（每檔股票一票）而不是市值加權，是刻意的選擇：市值加權會被少數幾檔
    權值股主導，而這個系統是全市場等權選股，等權的大盤才是它真正的比較基準。

    每個日期只用「當天及之前」的資料，跟其他特徵一樣不看未來。
    """
    daily_returns: dict[date, list[float]] = defaultdict(list)
    for bars in bars_by_code.values():
        for i in range(1, len(bars)):
            previous_close = bars[i - 1].close
            if previous_close:
                daily_returns[bars[i].trade_date].append((bars[i].close - previous_close) / previous_close * 100)

    series: dict[date, dict] = {}
    level = 100.0          # 合成的大盤指數，起點設 100 只是為了好讀
    levels: list[float] = []
    trading_days = sorted(daily_returns.keys())

    for i, day in enumerate(trading_days):
        returns = daily_returns[day]
        if not returns:
            continue
        market_return = sum(returns) / len(returns)
        breadth = sum(1 for r in returns if r > 0) / len(returns) * 100

        level *= 1 + market_return / 100
        levels.append(level)

        def change_over(window: int) -> float | None:
            """往回 window 個交易日的累積漲跌幅，不足就回 None。"""
            if len(levels) <= window:
                return None
            past = levels[-window - 1]
            return (level - past) / past * 100 if past else None

        ma20 = sum(levels[-20:]) / 20 if len(levels) >= 20 else None

        series[day] = {
            # 合成指數的水位。特徵用不到（水位本身沒有跨時間可比性），
            # 但算「未來 N 天的大盤報酬」需要它——那是 label 那邊的事
            "market_level": level,
            "market_return_1d": market_return,
            "market_return_5d": change_over(5),
            "market_return_20d": change_over(20),
            "market_breadth": breadth,
            "market_ma20_bias": (level - ma20) / ma20 * 100 if ma20 else None,
        }

    logger.info("build_market_series: %d 個交易日的大盤狀態", len(series))
    return series


def market_levels(series: dict[date, dict]) -> dict[date, float]:
    """從大盤序列抽出「日期 → 指數水位」，給 label 算未來報酬用。"""
    return {day: values["market_level"] for day, values in series.items()}



def build_feature_rows(
    db: Session,
    fetch_start: date,
    fetch_end: date,
    feature_start: date,
) -> tuple[list[dict], dict[str, list[DailyBar]]]:
    """組出 [feature_start, fetch_end] 之間所有 TWSE 股票的特徵列。

    fetch_start 要比 feature_start 早一段（暖身期），指標才算得出來；早於
    feature_start 的日子只用來暖身，不會產出特徵列。

    整條管線都是向量化的：價量特徵整欄一次算完（price_features），估值用
    merge_asof 做「取日期不晚於特徵日的最後一筆」的接合，籌碼面用一次 merge，
    大盤用日期 map。逐列的 Python 迴圈只剩最後把 DataFrame 轉成 dict 那一步。

    KD 是唯一還逐股票算的：它是遞迴平滑，而且跟策略引擎共用同一份實作，
    改寫成向量化會多出一份可能跟策略那邊不一致的邏輯。

    回傳 (特徵列, 原始日K)。每一列是 {stock_code, as_of_date, close, <各項特徵>...}，
    還沒有 label——label 需要「未來」的價格，交給 dataset.attach_labels 用同一份
    日K去算，職責才不會跟「只能看過去」的特徵混在一起。
    """
    bars_by_code = load_twse_bars(db, fetch_start, fetch_end)
    # 資料太短的股票連 MA20/KD 都不穩，整檔排除
    bars_by_code = {c: b for c, b in bars_by_code.items() if len(b) >= MIN_BARS_FOR_FEATURES}
    if not bars_by_code:
        return [], {}

    frame = build_price_frame(bars_by_code)
    features = compute_price_features(frame)
    combined = pd.concat([frame[["stock_code", "as_of_date"]], features], axis=1)

    # 暖身期的列到這裡才丟掉——前面要留著，滾動視窗才算得出正確的值
    position = frame.groupby("stock_code", sort=False).cumcount().to_numpy()
    keep = (combined["as_of_date"] >= feature_start) & (position + 1 >= MIN_BARS_FOR_FEATURES)
    combined = combined[keep].reset_index(drop=True)
    if combined.empty:
        return [], bars_by_code

    combined = _attach_kd(combined, bars_by_code)
    combined = _attach_valuations(combined, db, fetch_start, fetch_end)
    combined = _attach_market(combined, build_market_series(bars_by_code))
    combined = _attach_chips(combined, db, fetch_start, fetch_end, frame)

    # NaN 要換成 None：下游用 `value is None` 判斷缺值，NaN 會被當成有值
    combined = combined.astype(object).where(pd.notna(combined), None)
    rows = combined.to_dict("records")

    logger.info(
        "build_feature_rows: %s~%s 產出 %d 列特徵（涵蓋 %d 檔股票、%d 項特徵）",
        feature_start,
        fetch_end,
        len(rows),
        len(bars_by_code),
        len(FEATURE_KEYS),
    )
    return rows, bars_by_code


def _attach_kd(combined: pd.DataFrame, bars_by_code: dict[str, list[DailyBar]]) -> pd.DataFrame:
    """KD 逐股票算（遞迴平滑），再依 (代號, 日期) 併回來。"""
    records = []
    for code, bars in bars_by_code.items():
        for bar, (k, d) in zip(bars, compute_kd_series(bars)):
            records.append((code, bar.trade_date, k, d))
    kd = pd.DataFrame.from_records(records, columns=["stock_code", "as_of_date", "k_value", "d_value"])
    merged = combined.merge(kd, on=["stock_code", "as_of_date"], how="left")
    merged["k_minus_d"] = merged["k_value"] - merged["d_value"]
    return merged


def _attach_valuations(combined: pd.DataFrame, db: Session, start: date, end: date) -> pd.DataFrame:
    """估值快照是月頻的稀疏資料，取「日期不晚於特徵日」的最後一筆。

    merge_asof 的預設方向就是這個語意，而且它強制要求兩邊都依接合鍵排序——
    這正好也是「不看未來」的保證：它永遠不會往後找。
    """
    rows = (
        db.query(
            StockValuationHistory.stock_code,
            StockValuationHistory.as_of_date,
            StockValuationHistory.pe_ratio,
            StockValuationHistory.dividend_yield,
            StockValuationHistory.pb_ratio,
        )
        .filter(StockValuationHistory.as_of_date >= start, StockValuationHistory.as_of_date <= end)
        .all()
    )
    columns = ["stock_code", "as_of_date", "pe_ratio", "dividend_yield", "pb_ratio"]
    if not rows:
        for column in columns[2:]:
            combined[column] = None
        return combined

    valuations = pd.DataFrame.from_records(list(rows), columns=columns)
    valuations["as_of_date"] = pd.to_datetime(valuations["as_of_date"])
    valuations.sort_values(["as_of_date", "stock_code"], inplace=True)

    left = combined.copy()
    left["as_of_date"] = pd.to_datetime(left["as_of_date"])
    left.sort_values(["as_of_date", "stock_code"], inplace=True)

    merged = pd.merge_asof(left, valuations, on="as_of_date", by="stock_code", direction="backward")
    merged["as_of_date"] = merged["as_of_date"].dt.date
    return merged.sort_values(["stock_code", "as_of_date"]).reset_index(drop=True)


def _attach_market(combined: pd.DataFrame, market_series: dict[date, dict]) -> pd.DataFrame:
    """大盤狀態每個交易日只有一份，依日期 map 過去即可。"""
    for key in MARKET_FEATURE_KEYS:
        lookup = {day: values.get(key) for day, values in market_series.items()}
        combined[key] = combined["as_of_date"].map(lookup)

    # 相對強弱要等個股特徵算完才算得出來
    combined["relative_return_1d"] = combined["change_percent"] - combined["market_return_1d"]
    # roc_20 就是原本的 cumulative_change_20（同一個算式），移除重複後改用這個
    combined["relative_return_20d"] = combined["roc_20"] - combined["market_return_20d"]
    return combined


def _attach_chips(
    combined: pd.DataFrame, db: Session, start: date, end: date, frame: pd.DataFrame
) -> pd.DataFrame:
    """籌碼面特徵。買賣超一律除以成交量——原始股數在台積電（單日上億股）和
    小型股（幾十萬股）之間差好幾個數量級，不除的話模型學到的會是「這是不是
    大型股」，而不是「今天法人動作多大」。"""
    rows = (
        db.query(
            ChipDaily.stock_code,
            ChipDaily.trade_date,
            ChipDaily.foreign_net,
            ChipDaily.trust_net,
            ChipDaily.institution_net,
            ChipDaily.margin_balance,
        )
        .filter(ChipDaily.trade_date >= start, ChipDaily.trade_date <= end)
        .all()
    )
    if not rows:
        for key in CHIP_FEATURE_KEYS:
            combined[key] = None
        return combined

    chips = pd.DataFrame.from_records(
        list(rows),
        columns=["stock_code", "as_of_date", "foreign_net", "trust_net", "institution_net", "margin_balance"],
    )

    # 先在「完整的日K」上算滾動量，再併到已經濾過暖身期的 combined——
    # 反過來的話近 5 日的視窗會在切點處算錯
    base = frame[["stock_code", "as_of_date", "volume"]].merge(
        chips, on=["stock_code", "as_of_date"], how="left"
    )
    grouped = base.groupby("stock_code", sort=False)
    position = grouped.cumcount().to_numpy()

    net_5d = base["foreign_net"].rolling(5).sum().where(position >= 4)
    volume_5d = base["volume"].where(base["foreign_net"].notna()).rolling(5).sum().where(position >= 4)
    margin_past = grouped["margin_balance"].shift(5)

    derived = pd.DataFrame({"stock_code": base["stock_code"], "as_of_date": base["as_of_date"]})
    volume_safe = base["volume"].replace(0, np.nan)
    derived["foreign_net_ratio"] = base["foreign_net"] / volume_safe * 100
    derived["trust_net_ratio"] = base["trust_net"] / volume_safe * 100
    derived["institution_net_ratio"] = base["institution_net"] / volume_safe * 100
    derived["foreign_net_ratio_5d"] = net_5d / volume_5d.replace(0, np.nan) * 100
    derived["margin_change_5d"] = (
        (base["margin_balance"] - margin_past) / margin_past.replace(0, np.nan) * 100
    ).where(position >= 5)
    derived.replace([np.inf, -np.inf], np.nan, inplace=True)

    return combined.merge(derived, on=["stock_code", "as_of_date"], how="left")
