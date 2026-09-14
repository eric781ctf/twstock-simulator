"""美股與 ADR 特徵：把「昨晚美股怎麼走」拆成對每一檔台股各自不同的數字。

先前加進來的隔夜台指期實測沒有用，原因很清楚：六項裡有五項在同一天對全市場
是同一個值。這個系統做的是「當天挑前 10 名」的橫斷面排序，一個對所有股票同值
的欄位對排序沒有直接的區別力，只能讓樹去切「今天是什麼樣的日子」。

所以這裡的重點不是「多抓幾個美股指數」，而是把美股的漲跌**映射到個股**：

- 族群層級：費半漲 3%、道瓊跌 1% 的那一晚，半導體股跟水泥股拿到的數字不同
- 個股層級：台積電 ADR 昨晚的表現只屬於 2330，不屬於其他 999 檔

**日期對齊**：美股 session 日期 d 的那一節，在台北時間是 d 日 21:30 到 d+1 日
04:00。它落在台股 D 日收盤（13:30）之後、次一個台股交易日開盤（09:00）之前，
條件是 D <= d < next_tw_day(D)。平常這個區間裡只有一天，但台股連假時會有好
幾個美股交易日——那幾天的報酬要累乘起來，只取第一天會漏掉後面的。

跟隔夜台指期一樣，這些欄位裝的是基準日收盤「之後」才發生的事，只有
execution_mode='next_open' 下才合法，由 runner 硬性檢查。
"""

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OverseasDaily
from app.services.ingest.overseas_sync import ADR_TO_STOCK

logger = logging.getLogger(__name__)

# 市場級：同一天對全市場同值。留著是因為它們是下面那些欄位的基準線，
# 而且樹偶爾能靠它們做條件切分——但不要指望它們自己有橫斷面區別力
US_MARKET_FEATURE_KEYS = [
    "us_sox_overnight",
    "us_ndx_overnight",
    "us_dji_overnight",
    "us_vix_change",
]

# 橫斷面：同一天對不同股票是不同的值，這才是真正可能改變排序的部分
US_CROSS_FEATURE_KEYS = [
    "us_industry_overnight",
    "us_industry_excess",
    "adr_overnight_return",
    "adr_excess_over_industry",
    "us_gap_sensitivity",
    "us_gap_implied",
]

OVERSEAS_FEATURE_KEYS = US_MARKET_FEATURE_KEYS + US_CROSS_FEATURE_KEYS

OVERSEAS_FEATURE_LABELS: dict[str, str] = {
    "us_sox_overnight": "隔夜費城半導體指數漲跌幅",
    "us_ndx_overnight": "隔夜那斯達克 100 漲跌幅",
    "us_dji_overnight": "隔夜道瓊工業指數漲跌幅",
    "us_vix_change": "隔夜 VIX 變動點數",
    "us_industry_overnight": "隔夜對應族群美股指數漲跌幅",
    "us_industry_excess": "隔夜族群指數減大盤（族群特有的部分）",
    "adr_overnight_return": "隔夜自家 ADR 漲跌幅",
    "adr_excess_over_industry": "隔夜 ADR 減族群指數（個股特有的部分）",
    "us_gap_sensitivity": "個股開盤跳空對隔夜美股的 60 日敏感度",
    "us_gap_implied": "敏感度 × 今晚族群指數（預期跳空幅度）",
}

# 這幾個在同一天對全市場同值，做橫斷面排名或產業中性化時要跳過
MARKET_WIDE_KEYS = frozenset(US_MARKET_FEATURE_KEYS)

_SOX = "^SOX"
_NDX = "^NDX"
_DJI = "^DJI"
_GSPC = "^GSPC"
_VIX = "^VIX"

# 產業 → 拿哪一個美股指數當族群代理。
#
# 半導體單獨對費半：台股半導體跟 SOX 的連動遠強於跟大盤，把它併進那斯達克
# 等於把最強的一條連動稀釋掉。其餘電子相關對那斯達克 100，非電子對道瓊——
# 道瓊成分偏傳統產業，比 S&P 更接近台股傳產的性質。
_INDUSTRY_INDEX: dict[str, str] = {
    "24": _SOX,   # 半導體業
    "25": _NDX,   # 電腦及週邊設備業
    "26": _NDX,   # 光電業
    "27": _NDX,   # 通信網路業
    "28": _NDX,   # 電子零組件業
    "29": _NDX,   # 電子通路業
    "30": _NDX,   # 資訊服務業
    "31": _NDX,   # 其他電子業
    "34": _NDX,   # 電子商務
    "36": _NDX,   # 數位雲端
}
_DEFAULT_INDEX = _DJI

# ADR 的族群代理：拿它自己的產業對應。三檔半導體對費半，中華電對道瓊
_ADR_INDEX: dict[str, str] = {
    "TSM": _SOX,
    "UMC": _SOX,
    "ASX": _SOX,
    "CHT": _DJI,
}

_STOCK_TO_ADR = {stock: adr for adr, stock in ADR_TO_STOCK.items()}


def load_overseas(db: Session, start: date, end: date) -> pd.DataFrame:
    """讀成 (美股交易日 × 代號) 的收盤價寬表。"""
    rows = db.execute(
        select(OverseasDaily.symbol, OverseasDaily.trade_date, OverseasDaily.close)
        .where(OverseasDaily.trade_date >= start, OverseasDaily.trade_date <= end)
        .order_by(OverseasDaily.trade_date)
    ).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["symbol", "trade_date", "close"])
    return df.pivot(index="trade_date", columns="symbol", values="close").sort_index()


def build_overseas_series(
    db: Session, start: date, end: date, trading_days: list[date]
) -> dict[date, dict[str, float]]:
    """算出每個台股交易日一組「昨晚美股」的數字，回傳 {基準日 D: {代號: 報酬%}}。

    回傳的 key 是 Yahoo 代號（^SOX、TSM…），值是那一晚的累積報酬率（%）；
    ^VIX 是例外，回的是變動點數而不是報酬率——VIX 本身就是一個百分比刻度，
    再算它的百分比變化只會放大低檔時的雜訊。

    把「哪個指數對應哪檔股票」留給 attach 那一層，這裡只負責日期對齊。
    """
    wide = load_overseas(db, start, end)
    if wide.empty:
        logger.warning("build_overseas_series: %s~%s 沒有美股資料", start, end)
        return {}

    us_days = list(wide.index)
    out: dict[date, dict[str, float]] = {}

    for i, day in enumerate(trading_days[:-1]):
        nxt = trading_days[i + 1]
        # 落在 [D, next_tw_day) 的美股交易日。台股連假時會有兩天以上
        lo = np.searchsorted(us_days, day, side="left")
        hi = np.searchsorted(us_days, nxt, side="left")
        if hi <= lo:
            continue
        # 這一段的起點是區間第一天的「前一個」美股收盤——報酬要從那裡量起
        if lo == 0:
            continue

        base = wide.iloc[lo - 1]
        last = wide.iloc[hi - 1]

        values: dict[str, float] = {}
        for symbol in wide.columns:
            b, e = base.get(symbol), last.get(symbol)
            if b is None or e is None or not np.isfinite(b) or not np.isfinite(e):
                continue
            if symbol == _VIX:
                values[symbol] = float(e - b)
            elif b > 0:
                values[symbol] = float((e - b) / b * 100)
        if values:
            out[day] = values

    logger.info("build_overseas_series: %s~%s 產出 %d 個交易日的美股隔夜資訊", start, end, len(out))
    return out


def attach(
    combined: pd.DataFrame,
    series: dict[date, dict[str, float]],
    industry_by_code: dict[str, str],
) -> pd.DataFrame:
    """把美股隔夜資訊接到特徵表上，指數欄位依產業／ADR 對應到個股。"""
    dates = combined["as_of_date"]

    for key, symbol in (
        ("us_sox_overnight", _SOX),
        ("us_ndx_overnight", _NDX),
        ("us_dji_overnight", _DJI),
        ("us_vix_change", _VIX),
    ):
        combined[key] = dates.map({d: v.get(symbol) for d, v in series.items()})

    broad = dates.map({d: v.get(_GSPC) for d, v in series.items()})

    # 每檔股票該看哪個指數，先算成一欄代號，再依 (日期, 代號) 查值。
    # 逐列去查 dict 在一百多萬列上會慢到有感，分組 map 才吃得消
    proxy = combined["stock_code"].map(
        lambda code: _INDUSTRY_INDEX.get(industry_by_code.get(code, ""), _DEFAULT_INDEX)
    )
    combined["us_industry_overnight"] = _lookup(dates, proxy, series)
    combined["us_industry_excess"] = combined["us_industry_overnight"] - broad

    adr = combined["stock_code"].map(_STOCK_TO_ADR)
    combined["adr_overnight_return"] = _lookup(dates, adr, series)
    # ADR 減掉它自己族群的指數＝「這家公司昨晚跑贏同業多少」。直接用 ADR 報酬
    # 的話，裡面八成是整個族群一起漲跌，那部分 us_industry_overnight 已經講過了
    adr_proxy = adr.map(_ADR_INDEX)
    combined["adr_excess_over_industry"] = combined["adr_overnight_return"] - _lookup(
        dates, adr_proxy, series
    )

    # 敏感度由 builder 在截斷前算好塞進來，這裡只負責乘上「今晚」的族群指數。
    # 乘出來就是「預期明天開盤會被推高／壓低多少」
    combined["us_gap_implied"] = (
        combined["us_gap_sensitivity"] * combined["us_industry_overnight"]
    )
    return combined


_SENSITIVITY_WINDOW = 60
_SENSITIVITY_MIN_PERIODS = 30


def gap_sensitivity(
    frame: pd.DataFrame,
    series: dict[date, dict[str, float]],
    industry_by_code: dict[str, str],
    trading_days: list[date],
) -> pd.Series:
    """算「這檔股票的開盤跳空，對昨晚族群指數有多敏感」，再乘上今晚的指數。

    前面那幾個族群欄位只有三個相異值（費半／那斯達克／道瓊），同一組裡的
    幾百檔股票拿到完全一樣的數字，排序上分不出來。敏感度是讓每一檔都不同的
    那一步：同樣是半導體，有的股票費半漲 3% 它就跳空 2.5%，有的只有 0.8%。

    量的是**開盤跳空**而不是當日報酬，因為傳導路徑就是跳空：昨晚美股的資訊
    在 09:00 一次反映在開盤價上，盤中那段是台灣自己的事。

    對齊：台股 D 的跳空，對應的是 prev_tw_day(D) 那一列的隔夜欄位（也就是
    D 開盤前的那一晚）。今晚（D 這一列）的指數則是用來算 us_gap_implied，
    預測 D+1 的跳空——而 D+1 開盤正是 next_open 模式的進場點。

    **這裡預測的不是我們會賺的那一段。** label 從開盤(D+1) 起算，跳空在那
    之前就發生完了，買進價已經包含它。us_gap_implied 的用處是讓模型知道
    「這檔今天被推高／壓低了多少」，接下來要學的是延續還是回吐。
    """
    prev_day = {d: trading_days[i - 1] for i, d in enumerate(trading_days) if i > 0}

    proxy_of = lambda code: _INDUSTRY_INDEX.get(industry_by_code.get(code, ""), _DEFAULT_INDEX)
    proxy_full = frame["stock_code"].map(proxy_of)

    # 開盤跳空（%）：今天開盤相對昨天收盤。要在暖身期還沒截斷的 frame 上算，
    # 60 日滾動視窗才有前面那段歷史可用
    prev_close = frame.groupby("stock_code", sort=False)["close"].shift(1)
    gap = (frame["open"] - prev_close) / prev_close * 100

    # 昨晚的族群指數：先把 (日期, 指數) 查成一欄，再整體往前挪一個交易日
    yesterday = frame["as_of_date"].map(prev_day)
    driver = _lookup(yesterday, proxy_full, series)

    work = pd.DataFrame(
        {"stock_code": frame["stock_code"].to_numpy(), "y": gap.to_numpy(), "x": driver.to_numpy()}
    )
    work["xy"] = work["y"] * work["x"]
    work["xx"] = work["x"] * work["x"]
    grouped = work.groupby("stock_code", sort=False)
    kw = dict(window=_SENSITIVITY_WINDOW, min_periods=_SENSITIVITY_MIN_PERIODS)
    means = {c: grouped[c].transform(lambda v: v.rolling(**kw).mean()) for c in ("y", "x", "xy", "xx")}

    cov = means["xy"] - means["y"] * means["x"]
    var = means["xx"] - means["x"] * means["x"]
    sensitivity = (cov / var.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    return sensitivity


def _lookup(
    dates: pd.Series, symbols: pd.Series, series: dict[date, dict[str, float]]
) -> pd.Series:
    """依 (日期, 代號) 兩欄查值。代號是 NaN 的列（沒有 ADR 的股票）留 NaN。"""
    out = pd.Series(np.nan, index=dates.index, dtype=float)
    for symbol in symbols.dropna().unique():
        mask = symbols == symbol
        out.loc[mask] = dates[mask].map({d: v.get(symbol) for d, v in series.items()})
    return out
