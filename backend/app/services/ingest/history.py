"""日 K 線資料：TWSE 股票可從官方歷史 API 一次回補約 3 個月，
TPEx 沒有公開的多日歷史端點，只能靠每日同步逐日累積（見 stock_sync.py）。
"""

import asyncio
import logging
from datetime import date, timedelta

import httpx
from sqlalchemy.orm import Session

from app.models import DailyBar, Market, Stock

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 (twstock-simulator)"}
TWSE_STOCK_DAY_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
_RATE_LIMIT_STATUS_CODES = {428, 429}


class RateLimitedError(Exception):
    """TWSE 對 STOCK_DAY 端點的請求量開始回 428/429。這時候不該再繼續打，
    只會一路收到失敗回應——直接把整批回補任務中止，讓下一次排程（或下次
    重啟）自然接著補，而不是硬扛著把上千檔的失敗都跑完。"""


def to_float(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if s in ("", "--", "-", "X"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def to_int(raw) -> int:
    v = to_float(raw)
    return int(v) if v is not None else 0


def roc_slash_to_date(s: str) -> date | None:
    try:
        y, m, d = s.split("/")
        return date(int(y) + 1911, int(m), int(d))
    except (ValueError, AttributeError):
        return None


def roc_compact_to_date(s: str) -> date | None:
    """ROC 7 碼日期，例如 1150827 -> 2026-08-27。"""
    try:
        s = str(s)
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:7]))
    except (ValueError, IndexError):
        return None


def upsert_daily_bar(db: Session, stock_code: str, trade_date: date, o, h, l, c, v: int) -> None:
    if o is None or h is None or l is None or c is None:
        return
    existing = (
        db.query(DailyBar)
        .filter(DailyBar.stock_code == stock_code, DailyBar.trade_date == trade_date)
        .first()
    )
    if existing:
        existing.open, existing.high, existing.low, existing.close, existing.volume = o, h, l, c, v
    else:
        db.add(DailyBar(stock_code=stock_code, trade_date=trade_date, open=o, high=h, low=l, close=c, volume=v))


async def backfill_twse_history(
    db: Session,
    stock_code: str,
    months: int = 3,
    client: httpx.AsyncClient | None = None,
    request_delay: float = 0.0,
) -> int:
    """向 TWSE 官方歷史 API 回補過去 N 個月的日 K，僅適用上市股票。可傳入既有的
    httpx.AsyncClient 重複使用連線（見 stock_sync.backfill_all_twse_daily_bars
    對上千檔股票批次呼叫時，重用連線比每檔都重新握手快很多）；不傳的話維持
    原本「自己開一個」的行為，給單檔查詢的呼叫端（get_daily_history）用。
    request_delay 是每個月份請求之間的間隔秒數，批次回補時用來降低瞬間請求量。

    遇到 428/429（TWSE 開始限流）會直接拋出 RateLimitedError，不吞掉繼續跑——
    這種情況下越急著補完剩下的月份/股票只會一路收到更多失敗回應。"""
    today = date.today()
    count = 0
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=15, headers=_HEADERS)
    try:
        for i in range(months):
            if i > 0 and request_delay:
                await asyncio.sleep(request_delay)

            year = today.year
            month = today.month - i
            while month <= 0:
                month += 12
                year -= 1
            query_date = f"{year}{month:02d}01"
            try:
                resp = await client.get(
                    TWSE_STOCK_DAY_URL,
                    params={"response": "json", "date": query_date, "stockNo": stock_code},
                )
                if resp.status_code in _RATE_LIMIT_STATUS_CODES:
                    raise RateLimitedError(f"TWSE 回應 {resp.status_code}，疑似被限流")
                resp.raise_for_status()
                data = resp.json()
            except RateLimitedError:
                raise
            except Exception:
                logger.exception("backfill_twse_history failed for %s %s", stock_code, query_date)
                continue

            for row in data.get("data", []):
                # row: [日期, 成交股數, 成交金額, 開盤價, 最高價, 最低價, 收盤價, 漲跌價差, 成交筆數]
                trade_date = roc_slash_to_date(row[0])
                if trade_date is None:
                    continue
                o, h, l, c = to_float(row[3]), to_float(row[4]), to_float(row[5]), to_float(row[6])
                vol = to_int(row[1])
                upsert_daily_bar(db, stock_code, trade_date, o, h, l, c, vol)
                count += 1
    except RateLimitedError:
        if count:
            db.commit()  # 被擋之前已經拿到的資料還是留著，不要白做工
        raise
    finally:
        if owns_client:
            await client.aclose()
    if count:
        db.commit()
    return count


async def get_daily_history(db: Session, stock: Stock, months: int = 3) -> list[DailyBar]:
    cutoff = date.today() - timedelta(days=months * 31)
    existing = (
        db.query(DailyBar)
        .filter(DailyBar.stock_code == stock.code, DailyBar.trade_date >= cutoff)
        .order_by(DailyBar.trade_date.asc())
        .all()
    )

    if stock.market == Market.TWSE and len(existing) < 10:
        await backfill_twse_history(db, stock.code, months)
        existing = (
            db.query(DailyBar)
            .filter(DailyBar.stock_code == stock.code, DailyBar.trade_date >= cutoff)
            .order_by(DailyBar.trade_date.asc())
            .all()
        )
    return existing
