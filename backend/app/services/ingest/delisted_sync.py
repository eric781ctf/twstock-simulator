"""把已下市股票的上市日K補回來，修正「用今天的上市清單回推歷史」的倖存者偏誤。

**問題**：stocks 表只來自當天的官方上市清單，按日回補（backfill_twse_daily_bars_by_date）
又只寫清單裡有的代號。系統建立之前就下市的公司（併購消滅、KY 股下市、全額
交割後終止上市…）完全不存在，訓練、回測、事件研究看到的都是「活到今天的
股票」。抽樣比對：2020-01-02 TWSE 有成交的普通股 945 檔，本地只有 908 檔。

**做法**：同樣逐日打 MI_INDEX（一次一天、全市場），但不看清單——
- 普通股代號不在 stocks：建一筆 listing_status=delisted 的股票
- 當天本地沒有這檔的日K：補上（只新增，不覆寫既有資料）
- 處理完的日期記進 ingest_date_log，重跑從缺的地方接續

第二點順便修掉既有回補的洞：它用「當天已有 200 筆」判斷補過沒，清單後來才
加進來的代號（例如 1563、6949）在那些日期就永遠補不到。

**刻意不接排程**：全期間約 1,600 個交易日，照既有節奏要跑三個多小時，由人
決定什麼時候跑。限流處理沿用既有規則，被擋就停，不重試、不繞過。

執行（先用 --dry-run 看待處理天數與預估時間，不會發出任何請求）：
docker compose exec -e PYTHONPATH=/app backend python -m app.services.ingest.delisted_sync --start 2020-01-01 --dry-run
"""

import argparse
import asyncio
import logging
from collections import defaultdict
from datetime import date, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import LISTING_DELISTED, DailyBar, IngestDateLog, Market, Stock
from app.services.ingest.history import RateLimitedError
from app.services.ingest.stock_sync import _HEADERS, DAILY_BY_DATE_DELAY_SECONDS, EMPTY_WEEKDAY_ABORT
from app.services.ingest.twse_client import fetch_twse_daily_quotes_for_date
from app.services.ingest.universe import is_ordinary_stock

logger = logging.getLogger(__name__)

SOURCE = "twse_mi_index_universe"
# 本地明明有日K的交易日，TWSE 卻連續回空，幾乎可以確定是軟性限流
KNOWN_TRADING_DAY_EMPTY_ABORT = 3
# MI_INDEX 全市場回應很大，含下載的粗估秒數，只用來算預估時間
ESTIMATED_RESPONSE_SECONDS = 2.0


def pending_days(db: Session, start: date, end: date, monthly: bool = False) -> list[date]:
    """還沒處理過的平日。monthly＝每個月只挑一天（本地確定有開盤的那天），
    用來先快速掃出「有哪些下市股票」，之後再決定要不要逐日補齊。"""
    done = {
        d
        for (d,) in db.query(IngestDateLog.trade_date).filter(
            IngestDateLog.source == SOURCE, IngestDateLog.trade_date >= start, IngestDateLog.trade_date <= end
        )
    }
    weekdays = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    weekdays = [d for d in weekdays if d.weekday() < 5]
    if not monthly:
        return [d for d in weekdays if d not in done]

    local_days = set(_local_bar_counts(db, start, end))
    by_month: dict[tuple[int, int], list[date]] = defaultdict(list)
    for d in weekdays:
        by_month[(d.year, d.month)].append(d)
    picked = []
    for days in by_month.values():
        if any(d in done for d in days):
            continue
        trading = [d for d in days if d in local_days]
        picked.append(trading[0] if trading else days[0])
    return picked


def estimate_seconds(day_count: int, request_delay: float = DAILY_BY_DATE_DELAY_SECONDS) -> float:
    return day_count * (request_delay + ESTIMATED_RESPONSE_SECONDS)


def _local_bar_counts(db: Session, start: date, end: date) -> dict[date, int]:
    return dict(
        db.query(DailyBar.trade_date, func.count(DailyBar.id))
        .filter(DailyBar.trade_date >= start, DailyBar.trade_date <= end)
        .group_by(DailyBar.trade_date)
        .all()
    )


def store_day(db: Session, day: date, quotes: list[dict], stocks: dict[str, Stock]) -> dict:
    """寫入一天的結果並記錄這天處理過。stocks 會就地加入新建的下市股票。"""
    have = {c for (c,) in db.query(DailyBar.stock_code).filter(DailyBar.trade_date == day)}
    stats = {"new_stocks": 0, "bars": 0, "other_market": 0}
    bars = []
    for item in quotes:
        code = item["code"]
        if not is_ordinary_stock(code):
            continue
        stock = stocks.get(code)
        if stock is None:
            stock = Stock(
                code=code, name=item["name"], market=Market.TWSE, listing_status=LISTING_DELISTED, delisted_on=day
            )
            db.add(stock)
            stocks[code] = stock
            stats["new_stocks"] += 1
        elif stock.market != Market.TWSE:
            # 後來轉到上櫃的股票：主鍵只能掛一個市場，它在上市時期的歷史先不處理
            stats["other_market"] += 1
            continue
        if stock.listing_status == LISTING_DELISTED and (stock.delisted_on is None or day > stock.delisted_on):
            stock.delisted_on = day
        if code in have:
            continue
        bars.append(
            DailyBar(
                stock_code=code,
                trade_date=day,
                open=item["open"],
                high=item["high"],
                low=item["low"],
                close=item["close"],
                volume=item["volume"],
            )
        )
    db.flush()  # 新股票先進資料庫，日K的外鍵才對得上
    db.add_all(bars)
    stats["bars"] = len(bars)
    db.add(IngestDateLog(source=SOURCE, trade_date=day, row_count=len(quotes)))
    db.commit()
    return stats


async def backfill_universe_by_date(
    db: Session,
    start: date,
    end: date,
    monthly: bool = False,
    request_delay: float = DAILY_BY_DATE_DELAY_SECONDS,
) -> dict:
    days = pending_days(db, start, end, monthly)
    summary = {"pending": len(days), "processed": 0, "holidays": 0, "new_stocks": 0, "bars": 0, "other_market": 0,
               "stopped": None}
    if not days:
        return summary

    local_counts = _local_bar_counts(db, start, end)
    local_first, local_last = (min(local_counts), max(local_counts)) if local_counts else (None, None)
    stocks = {s.code: s for s in db.query(Stock).all()}
    logger.info(
        "backfill_universe_by_date: %s ~ %s 待處理 %d 天，預估 %.0f 分鐘",
        start, end, len(days), estimate_seconds(len(days), request_delay) / 60,
    )

    consecutive_empty = 0
    async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
        for i, day in enumerate(days):
            if i > 0:
                await asyncio.sleep(request_delay)
            try:
                quotes = await fetch_twse_daily_quotes_for_date(day.strftime("%Y%m%d"), client=client)
            except RateLimitedError:
                summary["stopped"] = f"被 TWSE 限流，停在 {day}"
                break

            if not quotes:
                known_trading = local_counts.get(day, 0) > 0
                covered = local_first is not None and local_first <= day <= local_last
                if covered and not known_trading:
                    # 本地資料涵蓋這段期間、這天卻完全沒有日K：確認是休市日，記下來下次不用再問
                    db.add(IngestDateLog(source=SOURCE, trade_date=day, row_count=0))
                    db.commit()
                    summary["holidays"] += 1
                    continue
                # 分不出是休市還是軟性限流（回 200 但內容是空的）。本地知道是
                # 交易日的，連續幾天就停；本地沒資料可對照的，沿用既有的平日門檻
                consecutive_empty += 1
                limit = KNOWN_TRADING_DAY_EMPTY_ABORT if known_trading else EMPTY_WEEKDAY_ABORT
                if consecutive_empty >= limit:
                    summary["stopped"] = f"連續 {consecutive_empty} 天拿到空資料（疑似被限流），停在 {day}"
                    break
                continue

            consecutive_empty = 0
            stats = store_day(db, day, quotes, stocks)
            summary["processed"] += 1
            for key, value in stats.items():
                summary[key] += value
            if summary["processed"] % 20 == 0:
                logger.info("backfill_universe_by_date: 進度 %d/%d（%s）%s", i + 1, len(days), day, summary)

    if summary["stopped"]:
        logger.warning("backfill_universe_by_date: %s；重跑會從缺的地方接續", summary["stopped"])
    logger.info("backfill_universe_by_date: 結束 %s", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="用 MI_INDEX 補回已下市上市股票的日K")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2020, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    parser.add_argument("--monthly", action="store_true", help="每月只抽一天，快速掃出下市股票清單")
    parser.add_argument("--dry-run", action="store_true", help="只列出待處理天數與預估時間，不發出請求")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    with SessionLocal() as db:
        days = pending_days(db, args.start, args.end, args.monthly)
        minutes = estimate_seconds(len(days)) / 60
        print(f"{args.start} ~ {args.end}{'（每月一天）' if args.monthly else ''}：待處理 {len(days)} 天，預估 {minutes:.0f} 分鐘")
        if args.dry_run or not days:
            return
        print(asyncio.run(backfill_universe_by_date(db, args.start, args.end, args.monthly)))


if __name__ == "__main__":
    main()
