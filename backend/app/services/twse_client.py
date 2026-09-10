"""台股報價與股票清單串接。

注意：mis.twse.com.tw 是非官方但廣泛使用的即時報價端點，有 3 requests / 5 秒的速率限制，
因此所有需要報價的股票代碼一律合併成單一請求（用 `|` 分隔），不逐檔呼叫。
"""

import logging
import time

import httpx

from app.services.history import RateLimitedError, roc_compact_to_date, to_float, to_int

logger = logging.getLogger(__name__)

MIS_QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_LISTED_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX_VALUATION_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TWSE_VALUATION_HISTORY_URL = "https://www.twse.com.tw/exchangeReport/BWIBBU_d"
TWSE_DAILY_QUOTES_URL = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
# 籌碼面：三大法人買賣超日報與信用交易餘額，兩支都是「一次一天、拿全市場」
TWSE_INSTITUTIONAL_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TWSE_QFIIS_URL = "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS"

_HEADERS = {"User-Agent": "Mozilla/5.0 (twstock-simulator)"}


def _market_prefix(market: str) -> str:
    return "tse_" if market == "TWSE" else "otc_"


async def fetch_quotes(codes_with_market: list[tuple[str, str]]) -> dict[str, dict]:
    """回傳 {code: {"price", "prev_close", "name", "open", "high", "low"}}。
    open/high/low 是「今天」的數字，就算這檔股票從沒被追蹤過、完全沒有分時歷史，
    第一次查詢也能立刻知道今天開高低的大致輪廓，只是看不到走過的路徑形狀。"""
    if not codes_with_market:
        return {}

    ex_ch = "|".join(f"{_market_prefix(m)}{code}.tw" for code, m in codes_with_market)
    # `_` 是給這個端點常見的快取破壞參數：ex_ch 對同一批股票每次輪詢都完全一樣，
    # 若網址不變，中間的快取層（CDN 或 mis.twse 自己的伺服器端快取）可能一直回同一份
    # 舊回應，導致盤中走勢圖出現「連續好幾小時同一個價格」的假象。
    params = {"ex_ch": ex_ch, "json": "1", "delay": "0", "_": str(int(time.time() * 1000))}

    try:
        async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as client:
            resp = await client.get(MIS_QUOTE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_quotes failed for codes=%s", [c for c, _ in codes_with_market])
        return {}

    result: dict[str, dict] = {}
    for row in data.get("msgArray", []):
        code = row.get("c")
        if not code:
            continue
        price = _parse_float(row.get("z"))
        prev_close = _parse_float(row.get("y"))
        result[code] = {
            "price": price if price is not None else prev_close,
            "prev_close": prev_close,
            "open": _parse_float(row.get("o")),
            "high": _parse_float(row.get("h")),
            "low": _parse_float(row.get("l")),
            "name": row.get("n"),
        }
    return result


def _parse_float(raw) -> float | None:
    if raw is None or raw == "-" or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


async def fetch_listed_stocks() -> list[dict]:
    """上市股票清單（來自 TWSE OpenAPI）。"""
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            resp = await client.get(TWSE_LISTED_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_listed_stocks failed")
        return []

    stocks = []
    for row in data:
        code = row.get("Code") or row.get("代號")
        name = row.get("Name") or row.get("名稱")
        if code and name:
            stocks.append(
                {
                    "code": code,
                    "name": name,
                    "market": "TWSE",
                    "trade_date": roc_compact_to_date(row.get("Date")),
                    "open": to_float(row.get("OpeningPrice")),
                    "high": to_float(row.get("HighestPrice")),
                    "low": to_float(row.get("LowestPrice")),
                    "close": to_float(row.get("ClosingPrice")),
                    "volume": to_int(row.get("TradeVolume")),
                }
            )
    return stocks


async def fetch_otc_stocks() -> list[dict]:
    """上櫃股票清單（來自 TPEx OpenAPI）。"""
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            resp = await client.get(TPEX_LISTED_URL)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_otc_stocks failed")
        return []

    stocks = []
    for row in data:
        code = row.get("Code") or row.get("代號") or row.get("SecuritiesCompanyCode")
        name = row.get("Name") or row.get("名稱") or row.get("CompanyName")
        if code and name:
            stocks.append(
                {
                    "code": code,
                    "name": name,
                    "market": "TPEX",
                    "trade_date": roc_compact_to_date(row.get("Date")),
                    "open": to_float(row.get("Open")),
                    "high": to_float(row.get("High")),
                    "low": to_float(row.get("Low")),
                    "close": to_float(row.get("Close")),
                    "volume": to_int(row.get("TradingShares")),
                }
            )
    return stocks


async def fetch_valuations() -> list[dict]:
    """全市場個股本益比、殖利率、股價淨值比（TWSE + TPEx），給搜尋頁的基本面區塊用。"""
    stocks: list[dict] = []

    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
            resp = await client.get(TWSE_VALUATION_URL)
            resp.raise_for_status()
            for row in resp.json():
                code = row.get("Code")
                if not code:
                    continue
                stocks.append(
                    {
                        "code": code,
                        "pe_ratio": to_float(row.get("PEratio")),
                        "dividend_yield": to_float(row.get("DividendYield")),
                        "pb_ratio": to_float(row.get("PBratio")),
                    }
                )
    except Exception:
        logger.exception("fetch_valuations (TWSE) failed")

    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
            resp = await client.get(TPEX_VALUATION_URL)
            resp.raise_for_status()
            for row in resp.json():
                code = row.get("SecuritiesCompanyCode")
                if not code:
                    continue
                stocks.append(
                    {
                        "code": code,
                        "pe_ratio": to_float(row.get("PriceEarningRatio")),
                        "dividend_yield": to_float(row.get("YieldRatio")),
                        "pb_ratio": to_float(row.get("PriceBookRatio")),
                    }
                )
    except Exception:
        logger.exception("fetch_valuations (TPEx) failed")

    return stocks


async def fetch_twse_daily_quotes_for_date(
    query_date: str, client: httpx.AsyncClient | None = None
) -> list[dict] | None:
    """某一天「全市場上市股票」的收盤行情。query_date 格式 YYYYMMDD（西元）。

    這支跟 STOCK_DAY 的方向正好相反：STOCK_DAY 是「一次一檔、拿一個月」，
    這支是「一次一天、拿全部股票」。回補歷史時方向選錯，請求數會差一個
    數量級——補 6 個月用這支只要約 120 次（每個交易日一次），用 STOCK_DAY
    則是 1380 檔 × 6 個月 ≈ 8000 次，後者不但慢，還會一直去撞 TWSE 的限流。

    回傳 None 代表「這天沒有資料」（週末、假日、或還沒收盤），跟「有資料但
    是空的」要分得開，呼叫端才知道該跳過而不是重試。
    """
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30, headers=_HEADERS)
    try:
        resp = await client.get(
            TWSE_DAILY_QUOTES_URL, params={"response": "json", "date": query_date, "type": "ALL"}
        )
        if resp.status_code in (428, 429):
            raise RateLimitedError(f"TWSE 回應 {resp.status_code}，疑似被限流")
        resp.raise_for_status()
        data = resp.json()
    except RateLimitedError:
        raise
    except Exception:
        logger.exception("fetch_twse_daily_quotes_for_date failed for %s", query_date)
        return None
    finally:
        if owns_client:
            await client.aclose()

    if data.get("stat") != "OK":
        return None  # 非交易日，TWSE 會回「很抱歉，沒有符合條件的資料!」

    # 回應裡有十來張表（各種指數、大盤統計…），要的是「每日收盤行情(全部)」那張
    table = next((t for t in data.get("tables", []) if "每日收盤行情" in (t.get("title") or "")), None)
    if not table:
        return None

    result = []
    for row in table.get("data") or []:
        # row: [證券代號, 證券名稱, 成交股數, 成交筆數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, ...]
        if len(row) < 9:
            continue
        o, h, l, c = to_float(row[5]), to_float(row[6]), to_float(row[7]), to_float(row[8])
        if o is None or h is None or l is None or c is None:
            continue  # 當天沒成交的證券，價格欄位會是 "--"
        result.append(
            {
                "code": row[0].strip(),
                "name": row[1].strip(),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": to_int(row[2]),
            }
        )
    return result


async def fetch_twse_valuations_for_date(query_date: str) -> list[dict]:
    """全市場（僅 TWSE 上市）在「某一天」的本益比、殖利率、股價淨值比快照，
    用來一次回補過去幾年的月度歷史。query_date 格式 YYYYMMDD（西元年）。
    TPEx 沒有公開的依日期查詢端點，回補不到，只能每日累積（見 stock_sync.py）。"""
    try:
        async with httpx.AsyncClient(timeout=20, headers=_HEADERS) as client:
            resp = await client.get(
                TWSE_VALUATION_HISTORY_URL,
                params={"response": "json", "date": query_date, "selectType": "ALL"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        logger.exception("fetch_twse_valuations_for_date failed for %s", query_date)
        return []

    rows = data.get("data") or []
    result = []
    for row in rows:
        # row: [證券代號, 證券名稱, 收盤價, 殖利率(%), 股利年度, 本益比, 股價淨值比, 財報年/季]
        if len(row) < 7:
            continue
        code = row[0]
        result.append(
            {
                "code": code,
                "pe_ratio": to_float(row[5]),
                "dividend_yield": to_float(row[3]),
                "pb_ratio": to_float(row[6]),
            }
        )
    return result


def _parse_int(raw) -> int | None:
    """TWSE 的數字帶千分位逗號，空白與 "--" 代表沒有資料。"""
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if not text or text in ("--", "---"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


async def _get_twse_json(url: str, params: dict, label: str, client: httpx.AsyncClient | None):
    """共用的 TWSE 取 JSON 流程：限流要能被上層辨識，其他錯誤回 None。"""
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30, headers=_HEADERS)
    try:
        resp = await client.get(url, params=params)
        if resp.status_code in (428, 429):
            raise RateLimitedError(f"TWSE 回應 {resp.status_code}，疑似被限流")
        resp.raise_for_status()
        return resp.json()
    except RateLimitedError:
        raise
    except Exception:
        logger.exception("%s failed for %s", label, params.get("date"))
        return None
    finally:
        if owns_client:
            await client.aclose()


async def fetch_twse_institutional_for_date(
    query_date: str, client: httpx.AsyncClient | None = None
) -> list[dict] | None:
    """某一天全市場的三大法人買賣超。query_date 格式 YYYYMMDD。

    回應包含權證等各種證券（單日一萬多列），呼叫端只會取自己追蹤的那些代號，
    所以這裡不過濾，保持「原樣回傳」讓職責單純。

    回 None 代表非交易日或抓取失敗，跟「有資料但空的」要分得開。
    """
    data = await _get_twse_json(
        TWSE_INSTITUTIONAL_URL,
        {"date": query_date, "selectType": "ALL", "response": "json"},
        "fetch_twse_institutional_for_date",
        client,
    )
    if not data or data.get("stat") != "OK":
        return None

    # 欄位順序來自 TWSE 的 fields：
    # [0]證券代號 [4]外陸資買賣超(不含外資自營商) [10]投信買賣超
    # [11]自營商買賣超 [18]三大法人買賣超
    result = []
    for row in data.get("data") or []:
        if len(row) < 19:
            continue
        result.append(
            {
                "stock_code": str(row[0]).strip(),
                "foreign_net": _parse_int(row[4]),
                "trust_net": _parse_int(row[10]),
                "dealer_net": _parse_int(row[11]),
                "institution_net": _parse_int(row[18]),
            }
        )
    return result


async def fetch_twse_margin_for_date(
    query_date: str, client: httpx.AsyncClient | None = None
) -> list[dict] | None:
    """某一天全市場的融資融券餘額（單位：交易單位／張）。"""
    data = await _get_twse_json(
        TWSE_MARGIN_URL,
        {"date": query_date, "selectType": "ALL", "response": "json"},
        "fetch_twse_margin_for_date",
        client,
    )
    if not data or data.get("stat") != "OK":
        return None

    # 回應有兩張表：全市場統計與個股彙總，要的是後者
    table = next((t for t in data.get("tables", []) if "彙總" in (t.get("title") or "")), None)
    if not table:
        return None

    # [0]代號 [6]融資今日餘額 [12]融券今日餘額
    # 融資與融券兩組欄位名稱重複（買進/賣出/前日餘額…），只能靠位置取
    result = []
    for row in table.get("data") or []:
        if len(row) < 13:
            continue
        result.append(
            {
                "stock_code": str(row[0]).strip(),
                "margin_balance": _parse_int(row[6]),
                "short_balance": _parse_int(row[12]),
            }
        )
    return result


async def fetch_twse_foreign_holding_for_date(
    query_date: str, client: httpx.AsyncClient | None = None
) -> list[dict] | None:
    """某一天全市場的外資及陸資持股比率。

    selectType 要用 ALLBUT0999 而不是 ALL——用 ALL 時這支端點會回 stat=OK
    但 data 是空的（欄位定義還在，資料沒有），很容易被誤判成「那天沒有資料」。
    """
    data = await _get_twse_json(
        TWSE_QFIIS_URL,
        {"date": query_date, "selectType": "ALLBUT0999", "response": "json"},
        "fetch_twse_foreign_holding_for_date",
        client,
    )
    if not data or data.get("stat") != "OK":
        return None

    # [0]證券代號 [3]發行股數 [5]全體外資及陸資持有股數 [7]全體外資及陸資持股比率
    result = []
    for row in data.get("data") or []:
        if len(row) < 8:
            continue
        ratio = row[7]
        try:
            ratio = float(str(ratio).replace(",", "").strip())
        except (TypeError, ValueError):
            ratio = None
        result.append({"stock_code": str(row[0]).strip(), "foreign_holding_ratio": ratio})
    return result
