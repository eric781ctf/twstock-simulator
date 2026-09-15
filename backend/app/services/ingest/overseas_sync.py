"""美股指數與台廠 ADR 的回補，資料來自 Yahoo Finance 的 chart 端點。

為什麼是這幾檔：台股（尤其電子）跟美股高度連動，而台股收盤後美股才開盤，
那一節的漲跌在隔天 09:00 開盤前是已知的。指數負責「族群層級」的連動
（費半對半導體、那斯達克對電子、道瓊對傳產），ADR 負責「個股層級」——
台積電 ADR 昨晚跌 3%，那是對 2330 這一檔的直接訊息，不是對全市場。

Yahoo 的 chart 端點一次就能把整段歷史拿回來（一個代號一個請求），所以這裡
沒有像 TWSE／期交所那樣的逐日或逐月迴圈，回補跟每日更新走同一條路徑。
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import OverseasDaily

logger = logging.getLogger(__name__)

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# 沒有 User-Agent 會被擋掉
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 指數：族群層級的連動來源
INDEX_SYMBOLS = ["^SOX", "^NDX", "^DJI", "^GSPC", "^VIX"]

# ADR：個股層級。對應到的是同一家公司在台灣的掛牌代號
ADR_TO_STOCK: dict[str, str] = {
    "TSM": "2330",   # 台積電
    "UMC": "2303",   # 聯電
    "ASX": "3711",   # 日月光投控
    "CHT": "2412",   # 中華電
}

SYMBOLS = INDEX_SYMBOLS + list(ADR_TO_STOCK)

# Yahoo 沒有公布速率上限，但連續打十個請求沒有間隔遲早會被擋。
# 一秒一個對「十個代號、一天跑一次」來說綽綽有餘
REQUEST_DELAY_SECONDS = 1.0


async def _fetch(client: httpx.AsyncClient, symbol: str, start: date, end: date) -> list[dict]:
    """抓單一代號 [start, end] 的日線，回傳 [{trade_date, open, ...}]。"""
    params = {
        "period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
        # 多給一天，避免時區換算把最後一天切掉
        "period2": int(
            datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp() + 86400
        ),
        "interval": "1d",
    }
    response = await client.get(CHART_URL.format(symbol=symbol), params=params)
    response.raise_for_status()
    payload = response.json()

    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        error = (payload.get("chart") or {}).get("error")
        raise ValueError(f"{symbol} 沒有回傳資料：{error}")

    block = result[0]
    stamps = block.get("timestamp") or []
    quote = ((block.get("indicators") or {}).get("quote") or [{}])[0]

    rows: list[dict] = []
    for i, stamp in enumerate(stamps):
        close = _at(quote.get("close"), i)
        if close is None:
            # 收盤價是唯一必要的欄位（所有特徵都從它算）。Yahoo 偶爾會給出
            # 一整列 null 的佔位資料，那種列留著只會在下游變成假的缺值
            continue
        rows.append(
            {
                # 時間戳是該交易日美東 09:30 的 UTC 秒數，轉回 UTC 日期就是美股交易日
                "trade_date": datetime.fromtimestamp(stamp, timezone.utc).date(),
                "open": _at(quote.get("open"), i),
                "high": _at(quote.get("high"), i),
                "low": _at(quote.get("low"), i),
                "close": close,
                "volume": _at(quote.get("volume"), i),
            }
        )
    return rows


def _at(series, index: int):
    if not series or index >= len(series):
        return None
    return series[index]


def _store(db: Session, symbol: str, rows: list[dict]) -> int:
    """寫入，已存在的日期就更新。

    用 upsert 而不是「先查再決定」：Yahoo 會回修正後的歷史值（尤其是拆股與
    股息調整之後），直接覆蓋才不會讓資料庫停在舊的一版。
    """
    if not rows:
        return 0
    values = [{"symbol": symbol, **row} for row in rows]
    statement = insert(OverseasDaily).values(values)
    statement = statement.on_conflict_do_update(
        index_elements=["symbol", "trade_date"],
        set_={
            "open": statement.excluded.open,
            "high": statement.excluded.high,
            "low": statement.excluded.low,
            "close": statement.excluded.close,
            "volume": statement.excluded.volume,
        },
    )
    db.execute(statement)
    db.commit()
    return len(values)


async def backfill(db: Session, start: date, end: date, symbols: list[str] | None = None) -> dict:
    """回補 [start, end] 的所有代號。一個代號一個請求。"""
    targets = symbols or SYMBOLS
    total = 0
    failed: list[str] = []
    logger.info("overseas backfill: %s ~ %s 共 %d 個代號", start, end, len(targets))

    async with httpx.AsyncClient(timeout=60, headers=HEADERS, follow_redirects=True) as client:
        for i, symbol in enumerate(targets):
            if i:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
            try:
                rows = await _fetch(client, symbol, start, end)
            except Exception:
                logger.exception("overseas backfill: %s 抓取失敗，跳過", symbol)
                failed.append(symbol)
                continue
            written = _store(db, symbol, rows)
            total += written
            logger.info("overseas %s：寫入 %d 列", symbol, written)

    logger.info("overseas backfill 完成，共寫入 %d 列，失敗 %d 個代號", total, len(failed))
    return {"written": total, "symbols": len(targets), "failed": failed}


async def sync_recent(db: Session, days: int = 10) -> dict:
    """補最近幾天。Yahoo 一次回整段，抓短一點只是為了少傳一點資料。"""
    today = datetime.now(timezone.utc).date()
    return await backfill(db, today - timedelta(days=days), today)


def coverage(db: Session) -> dict:
    """每個代號目前涵蓋到哪裡，給管理頁顯示。"""
    rows = db.execute(
        select(
            OverseasDaily.symbol,
            func.count(OverseasDaily.id),
            func.min(OverseasDaily.trade_date),
            func.max(OverseasDaily.trade_date),
        ).group_by(OverseasDaily.symbol)
    ).all()
    by_symbol = {
        symbol: {"rows": count, "start": start, "end": end}
        for symbol, count, start, end in rows
    }
    return {
        "symbols": [
            {
                "symbol": symbol,
                "kind": "adr" if symbol in ADR_TO_STOCK else "index",
                "stock_code": ADR_TO_STOCK.get(symbol),
                **by_symbol.get(symbol, {"rows": 0, "start": None, "end": None}),
            }
            for symbol in SYMBOLS
        ],
        "total_rows": sum(v["rows"] for v in by_symbol.values()),
        "missing": [s for s in SYMBOLS if s not in by_symbol],
    }
