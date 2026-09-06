import asyncio
import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DailyBar, Market, Stock, StockValuationHistory
from app.services import backfill_status
from app.services.history import RateLimitedError, backfill_twse_history, upsert_daily_bar
from app.services.twse_client import (
    fetch_listed_stocks,
    fetch_otc_stocks,
    fetch_twse_daily_quotes_for_date,
    fetch_twse_valuations_for_date,
    fetch_valuations,
)

logger = logging.getLogger(__name__)

VALUATION_BACKFILL_MONTHS = 36
DAILY_BAR_BACKFILL_MONTHS = 3
DAILY_BAR_MIN_BARS = 40  # 一季約 60 個交易日，抓「明顯不足」的門檻不用抓到剛好
DAILY_BAR_BATCH_SIZE = 20
DAILY_BAR_BATCH_DELAY_SECONDS = 1200.0
DAILY_BAR_REQUEST_DELAY_SECONDS = 10.0  # 同一檔股票內，每個月份請求之間的間隔
DAILY_BAR_STOCK_DELAY_SECONDS = 60.0  # 批次內，股票跟股票之間的間隔
DAILY_BAR_MAX_PER_RUN = 100  # 每次排程/啟動最多處理幾檔，其餘留給下一次
_HEADERS = {"User-Agent": "Mozilla/5.0 (twstock-simulator)"}


async def sync_stocks(db: Session) -> int:
    """同步上市+上櫃股票清單到本地 stocks 表，並順便把當日 OHLC 存進 daily_bars（
    TPEx 股票沒有多日歷史 API，只能靠這個每日呼叫逐日累積）。回傳同步筆數。

    分兩階段處理並整批查詢，避免對上萬檔股票逐筆查詢資料庫（太慢），
    也確保 stocks 先 flush 進資料庫，daily_bars 的外鍵才不會失敗。
    """
    listed = await fetch_listed_stocks()
    otc = await fetch_otc_stocks()
    all_stocks = listed + otc

    if not all_stocks:
        logger.warning("sync_stocks: 外部 API 無回傳資料，略過本次同步")
        return 0

    existing_stocks = {s.code: s for s in db.query(Stock).all()}
    count = 0
    for item in all_stocks:
        code = item["code"]
        if code in existing_stocks:
            existing_stocks[code].name = item["name"]
            existing_stocks[code].market = Market(item["market"])
        else:
            stock = Stock(code=code, name=item["name"], market=Market(item["market"]))
            db.add(stock)
            existing_stocks[code] = stock
        count += 1

    db.flush()

    bar_items = [item for item in all_stocks if item.get("trade_date")]
    bar_codes = [item["code"] for item in bar_items]
    existing_bars = {
        (b.stock_code, b.trade_date): b
        for b in (db.query(DailyBar).filter(DailyBar.stock_code.in_(bar_codes)).all() if bar_codes else [])
    }

    for item in bar_items:
        o, h, l, c = item.get("open"), item.get("high"), item.get("low"), item.get("close")
        if o is None or h is None or l is None or c is None:
            continue
        volume = item.get("volume") or 0
        key = (item["code"], item["trade_date"])
        if key in existing_bars:
            bar = existing_bars[key]
            bar.open, bar.high, bar.low, bar.close, bar.volume = o, h, l, c, volume
        else:
            db.add(
                DailyBar(
                    stock_code=item["code"],
                    trade_date=item["trade_date"],
                    open=o,
                    high=h,
                    low=l,
                    close=c,
                    volume=volume,
                )
            )

    db.commit()
    logger.info("sync_stocks: 同步完成，共 %d 檔", count)
    return count


def _upsert_valuation_snapshot(db: Session, as_of: date, items: list[dict], known_codes: set[str]) -> int:
    items = [item for item in items if item["code"] in known_codes]
    if not items:
        return 0

    codes = [i["code"] for i in items]
    existing = {
        v.stock_code: v
        for v in db.query(StockValuationHistory)
        .filter(StockValuationHistory.as_of_date == as_of, StockValuationHistory.stock_code.in_(codes))
        .all()
    }

    for item in items:
        code = item["code"]
        if code in existing:
            v = existing[code]
            v.pe_ratio, v.dividend_yield, v.pb_ratio = item["pe_ratio"], item["dividend_yield"], item["pb_ratio"]
        else:
            db.add(
                StockValuationHistory(
                    stock_code=code,
                    as_of_date=as_of,
                    pe_ratio=item["pe_ratio"],
                    dividend_yield=item["dividend_yield"],
                    pb_ratio=item["pb_ratio"],
                )
            )
    return len(items)


async def sync_valuations(db: Session) -> int:
    """同步今天的本益比、殖利率、股價淨值比快照到 stock_valuation_history。
    必須在 sync_stocks 之後呼叫，確保 stocks 表已經有對應的股票代碼（外鍵）。
    TWSE 股票另外有 backfill_valuation_history 回補歷史，這裡主要是讓 TPEx
    股票（沒有依日期查詢的公開端點）逐日累積出自己的歷史。"""
    items = await fetch_valuations()
    if not items:
        logger.warning("sync_valuations: 外部 API 無回傳資料，略過本次同步")
        return 0

    known_codes = {c for (c,) in db.query(Stock.code).all()}
    count = _upsert_valuation_snapshot(db, date.today(), items, known_codes)
    db.commit()
    logger.info("sync_valuations: 同步完成，共 %d 檔", count)
    return count


async def backfill_valuation_history(db: Session, months: int = VALUATION_BACKFILL_MONTHS) -> int:
    """回補 TWSE 上市股票過去約 N 個月的本益比／殖利率／股價淨值比月度快照
    （用官方「依日期查詢」端點，一次查一天可以拿到全部上市股票，效率很高）。
    TPEx 沒有這種依日期查詢的公開端點，回補不到，只能每日累積。

    只在資料明顯不足時才執行（用「歷史最早日期是不是夠久遠」判斷），
    避免每次容器重啟都重新打幾十次外部 API。
    """
    cutoff = date.today() - timedelta(days=months * 30)
    earliest = db.query(StockValuationHistory.as_of_date).order_by(StockValuationHistory.as_of_date.asc()).first()
    if earliest and earliest[0] <= cutoff + timedelta(days=45):
        logger.info("backfill_valuation_history: 已有足夠歷史資料（最早 %s），略過回補", earliest[0])
        return 0

    known_codes = {c for (c,) in db.query(Stock.code).all()}
    total = 0
    today = date.today()

    for i in range(months):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        query_date = f"{year}{month:02d}05"  # 每月 5 號附近，盡量避開週末

        items = await fetch_twse_valuations_for_date(query_date)
        if not items:
            continue
        count = _upsert_valuation_snapshot(db, date(year, month, 5), items, known_codes)
        total += count

    db.commit()
    logger.info("backfill_valuation_history: 回補完成，共寫入 %d 筆快照", total)
    return total


DAILY_BY_DATE_DELAY_SECONDS = 5.0  # 逐日回補的請求間隔；一天一次請求，這個節奏遠低於限流門檻
DAILY_BY_DATE_MIN_ROWS = 200  # 某一天本地已有這麼多筆上市日K，就當作那天補過了


async def backfill_twse_daily_bars_by_date(
    db: Session,
    start: date,
    end: date,
    request_delay: float = DAILY_BY_DATE_DELAY_SECONDS,
) -> int:
    """逐「日」回補全市場上市股票的日K（跟 backfill_all_twse_daily_bars 逐「檔」
    回補相對）。

    方向選對，請求數差一個數量級：TWSE 的 MI_INDEX 端點一次就回傳某一天全部
    上市股票的開高低收量，所以補 6 個月只要約 120 次請求（每個交易日一次），
    而逐檔的 STOCK_DAY 要 1380 檔 × 6 個月 ≈ 8000 次。少打 98% 的請求，自然
    也就不會一直去撞限流——這比想辦法繞過限流正確得多。

    已經有足夠資料的日期會直接跳過，所以重跑不會浪費請求；週末假日 TWSE 會回
    「沒有符合條件的資料」，也一樣跳過。
    """
    known_codes = {c for (c,) in db.query(Stock.code).filter(Stock.market == Market.TWSE).all()}
    if not known_codes:
        backfill_status.finish(backfill_status.PHASE_COMPLETED, "本地還沒有上市股票清單")
        return 0

    # 先問清楚哪些日期已經補過，避免重跑時重複打同樣的請求
    existing_counts = dict(
        db.query(DailyBar.trade_date, func.count(DailyBar.id))
        .filter(DailyBar.trade_date >= start, DailyBar.trade_date <= end)
        .group_by(DailyBar.trade_date)
        .all()
    )

    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    # 週末直接排除，不用浪費請求去問 TWSE
    candidate_days = [d for d in all_days if d.weekday() < 5]
    pending_days = [d for d in candidate_days if existing_counts.get(d, 0) < DAILY_BY_DATE_MIN_ROWS]

    backfill_status.begin(len(pending_days))
    if not pending_days:
        backfill_status.finish(backfill_status.PHASE_COMPLETED, f"{start} ~ {end} 的日K都已經補齊了")
        return 0

    backfill_status.set_batch(len(pending_days), len(pending_days))
    logger.info(
        "backfill_twse_daily_bars_by_date: %s ~ %s 共 %d 個待補日期（已跳過 %d 個補過的與週末）",
        start,
        end,
        len(pending_days),
        len(candidate_days) - len(pending_days),
    )

    written = 0
    processed = 0
    try:
        async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as client:
            for i, day in enumerate(pending_days):
                if i > 0:
                    await _throttled_sleep(request_delay, "每個交易日之間的間隔")

                backfill_status.set_running(day.isoformat(), processed, written)
                try:
                    quotes = await fetch_twse_daily_quotes_for_date(day.strftime("%Y%m%d"), client=client)
                except RateLimitedError:
                    logger.warning("backfill_twse_daily_bars_by_date: 被 TWSE 限流，在 %s 中止", day)
                    backfill_status.finish(
                        backfill_status.PHASE_RATE_LIMITED,
                        f"被 TWSE 限流，本輪補到 {day} 為止（已寫入 {written} 筆），剩下的留給下次",
                    )
                    return written

                processed += 1
                if not quotes:
                    continue  # 非交易日

                for item in quotes:
                    if item["code"] not in known_codes:
                        continue  # 權證、債券之類不在我們的股票清單裡
                    upsert_daily_bar(
                        db, item["code"], day, item["open"], item["high"], item["low"], item["close"], item["volume"]
                    )
                    written += 1
                db.commit()
    except Exception as e:
        logger.exception("backfill_twse_daily_bars_by_date: 本輪中斷")
        backfill_status.finish(backfill_status.PHASE_FAILED, str(e)[:200])
        raise

    backfill_status.set_running("", processed, written)
    backfill_status.finish(
        backfill_status.PHASE_COMPLETED,
        f"本輪處理 {processed} 個交易日、寫入 {written} 筆日K（{start} ~ {end}）",
    )
    logger.info("backfill_twse_daily_bars_by_date: 完成 %d 個日期、寫入 %d 筆", processed, written)
    return written


async def backfill_twse_to_target(db: Session) -> int:
    """把 TWSE 日K補到 admin 設定的目標月數那麼久以前。

    啟動、每日排程、admin 手動觸發三個進入點都走這裡，行為才會一致——
    不然「手動按的」跟「排程跑的」用不同策略，補出來的資料深度會對不起來。
    """
    from app.services.app_config import get_target_backfill_months

    months = get_target_backfill_months(db)
    end = date.today()
    start = end - timedelta(days=months * 31)
    return await backfill_twse_daily_bars_by_date(db, start, end)


async def _throttled_sleep(seconds: float, reason: str) -> None:
    """睡覺前先把「在等什麼、要等多久」記進狀態，前端才能顯示倒數，而不是
    讓使用者看著一個完全靜止的畫面猜系統是不是掛了。"""
    backfill_status.begin_wait(seconds, reason)
    await asyncio.sleep(seconds)


async def backfill_all_twse_daily_bars(
    db: Session,
    months: int = DAILY_BAR_BACKFILL_MONTHS,
    batch_size: int = DAILY_BAR_BATCH_SIZE,
    delay_seconds: float = DAILY_BAR_BATCH_DELAY_SECONDS,
    max_per_run: int = DAILY_BAR_MAX_PER_RUN,
) -> int:
    """幫「所有」上市股票回補約 months 個月的日 K 線，不像 sync_stocks 每天只拿
    今天一筆——TWSE 的 STOCK_DAY 是單檔查詢端點，沒有官方的「依日期查全市場」
    版本可用，全市場要補齊只能一檔一檔打。股票跟股票之間、同一檔股票的月份
    請求之間都刻意加了延遲，每 batch_size 檔再多休息一段更長的時間，避免對
    TWSE 送出太密集的請求（先前實測過瞬間量太大會被回 428 限流）。

    每次執行最多只處理 max_per_run 檔，不是把 targets 全部做完——targets
    可能有上千檔，就算有節流，一次執行也可能長達數小時，乾脆限制單次執行的
    份量，讓它自然分散到很多天，而不是仰賴中途被限流才被迫中斷。

    只挑「本地資料明顯不足」的股票補（daily_bars 少於 DAILY_BAR_MIN_BARS 筆），
    已經補過的下次執行會自動跳過，全市場回補完成前每天都會處理到不同的股票。

    如果還是被 TWSE 限流（RateLimitedError），立刻整批中止、不再繼續打——
    剩下沒補到的股票下次執行（明天的排程，或下次重啟）會因為還是「資料不足」
    被重新排進 targets，之後自然接著補，用多跑幾天的方式換取不要被封鎖。"""
    cutoff = date.today() - timedelta(days=months * 31 + 10)
    backfill_status.begin(0)

    twse_codes = [c for (c,) in db.query(Stock.code).filter(Stock.market == Market.TWSE).all()]
    if not twse_codes:
        backfill_status.finish(backfill_status.PHASE_COMPLETED, "本地還沒有上市股票清單")
        return 0

    bar_counts = dict(
        db.query(DailyBar.stock_code, func.count(DailyBar.id))
        .filter(DailyBar.stock_code.in_(twse_codes), DailyBar.trade_date >= cutoff)
        .group_by(DailyBar.stock_code)
        .all()
    )
    all_targets = [code for code in twse_codes if bar_counts.get(code, 0) < DAILY_BAR_MIN_BARS]
    if not all_targets:
        logger.info("backfill_all_twse_daily_bars: 全部上市股票資料都已足夠，略過")
        backfill_status.finish(backfill_status.PHASE_COMPLETED, "全部上市股票的資料都已足夠")
        return 0

    targets = all_targets[:max_per_run]
    logger.info(
        "backfill_all_twse_daily_bars: 全部還需要回補 %d 檔上市股票，本次處理前 %d 檔",
        len(all_targets),
        len(targets),
    )
    backfill_status.set_batch(len(targets), len(all_targets))
    total = 0
    processed = 0
    try:
        async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
            for i, code in enumerate(targets):
                if i > 0:
                    await _throttled_sleep(DAILY_BAR_STOCK_DELAY_SECONDS, "股票之間的間隔")
                    if i % batch_size == 0:
                        await _throttled_sleep(delay_seconds, f"每 {batch_size} 檔的長休息")

                backfill_status.set_running(code, processed, total)
                try:
                    total += await backfill_twse_history(
                        db, code, months, client=client, request_delay=DAILY_BAR_REQUEST_DELAY_SECONDS
                    )
                    processed += 1
                except RateLimitedError:
                    logger.warning(
                        "backfill_all_twse_daily_bars: 被 TWSE 限流，中止本次回補（已處理 %d/%d 檔），剩下的留給下次排程",
                        processed,
                        len(targets),
                    )
                    backfill_status.set_running(code, processed, total)
                    backfill_status.finish(
                        backfill_status.PHASE_RATE_LIMITED,
                        f"被 TWSE 限流，本輪在第 {processed}/{len(targets)} 檔中止，剩下的留給下次排程",
                    )
                    return total
                except Exception:
                    logger.exception("backfill_all_twse_daily_bars: %s 回補失敗", code)
                    processed += 1
    except Exception as e:
        logger.exception("backfill_all_twse_daily_bars: 本輪回補中斷")
        backfill_status.finish(backfill_status.PHASE_FAILED, str(e)[:200])
        raise

    logger.info(
        "backfill_all_twse_daily_bars: 本次處理 %d/%d 檔、寫入 %d 筆日K（全市場還剩 %d 檔待補）",
        processed,
        len(targets),
        total,
        len(all_targets) - processed,
    )
    backfill_status.set_running("", processed, total)
    backfill_status.finish(
        backfill_status.PHASE_COMPLETED,
        f"本輪處理 {processed} 檔、寫入 {total} 筆日K，全市場還剩 {len(all_targets) - processed} 檔待補",
    )
    return total


_BAR_COUNT_BUCKETS = [
    (0, 0, "0"),
    (1, 9, "1-9"),
    (10, 39, "10-39"),
    (40, 59, "40-59"),
    (60, None, "60+"),
]


def _bucketize_bar_counts(counts: list[int]) -> list[dict]:
    bucket_counts = {label: 0 for _, _, label in _BAR_COUNT_BUCKETS}
    for count in counts:
        for lo, hi, label in _BAR_COUNT_BUCKETS:
            if count >= lo and (hi is None or count <= hi):
                bucket_counts[label] += 1
                break
    return [{"label": label, "count": bucket_counts[label]} for _, _, label in _BAR_COUNT_BUCKETS]


def get_twse_earliest_bar_date(db: Session) -> date | None:
    """目前 TWSE 上市股票本地日K回補到多早——用來讓 admin 判斷「要不要繼續往前補」。
    只看 TWSE，因為 TPEx 沒有回補機制、興櫃根本不在系統範圍內。"""
    row = (
        db.query(func.min(DailyBar.trade_date))
        .join(Stock, Stock.code == DailyBar.stock_code)
        .filter(Stock.market == Market.TWSE)
        .scalar()
    )
    return row


def get_daily_bar_stats(db: Session) -> dict:
    """給管理後台看的資料完整度統計：每個市場有幾檔股票、日K筆數落在哪個
    區間、有幾檔已經達到「足夠」（>= DAILY_BAR_MIN_BARS）的門檻。TWSE 的
    「足夠」通常代表已經被 backfill_all_twse_daily_bars 回補過；TPEx 沒有
    回補機制，純粹是逐日累積的結果，前端呈現時措辭要分開講。"""
    stock_markets = dict(db.query(Stock.code, Stock.market).all())
    bar_counts = dict(db.query(DailyBar.stock_code, func.count(DailyBar.id)).group_by(DailyBar.stock_code).all())

    result = {}
    for market in (Market.TWSE, Market.TPEX):
        codes = [code for code, m in stock_markets.items() if m == market]
        counts = [bar_counts.get(code, 0) for code in codes]
        sufficient = sum(1 for c in counts if c >= DAILY_BAR_MIN_BARS)
        result[market.value.lower()] = {
            "total_stocks": len(codes),
            "sufficient": sufficient,
            "insufficient": len(codes) - sufficient,
            "buckets": _bucketize_bar_counts(counts),
        }
    return result
