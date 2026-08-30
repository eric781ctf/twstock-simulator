"""台股報價與股票清單串接。

注意：mis.twse.com.tw 是非官方但廣泛使用的即時報價端點，有 3 requests / 5 秒的速率限制，
因此所有需要報價的股票代碼一律合併成單一請求（用 `|` 分隔），不逐檔呼叫。
"""

import logging
import time

import httpx

from app.services.history import roc_compact_to_date, to_float, to_int

logger = logging.getLogger(__name__)

MIS_QUOTE_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_LISTED_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_VALUATION_URL = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TPEX_VALUATION_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis"
TWSE_VALUATION_HISTORY_URL = "https://www.twse.com.tw/exchangeReport/BWIBBU_d"

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
