import asyncio
import logging
from datetime import date, timedelta

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DailyBar, Market, Stock, StockValuationHistory
from app.services.history import backfill_twse_history
from app.services.twse_client import (
    fetch_listed_stocks,
    fetch_otc_stocks,
    fetch_twse_valuations_for_date,
    fetch_valuations,
)

logger = logging.getLogger(__name__)

VALUATION_BACKFILL_MONTHS = 36
DAILY_BAR_BACKFILL_MONTHS = 3
DAILY_BAR_MIN_BARS = 40  # 一季約 60 個交易日，抓「明顯不足」的門檻不用抓到剛好
DAILY_BAR_BATCH_SIZE = 20
DAILY_BAR_BATCH_DELAY_SECONDS = 3.0
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


async def backfill_all_twse_daily_bars(
    db: Session,
    months: int = DAILY_BAR_BACKFILL_MONTHS,
    batch_size: int = DAILY_BAR_BATCH_SIZE,
    delay_seconds: float = DAILY_BAR_BATCH_DELAY_SECONDS,
) -> int:
    """幫「所有」上市股票回補約 months 個月的日 K 線，不像 sync_stocks 每天只拿
    今天一筆——TWSE 的 STOCK_DAY 是單檔查詢端點，沒有官方的「依日期查全市場」
    版本可用，全市場要補齊只能一檔一檔打。分批（batch_size 檔一組）、批次間
    休息 delay_seconds 秒，避免瞬間對 TWSE 送出上千個請求。

    只挑「本地資料明顯不足」的股票補（daily_bars 少於 DAILY_BAR_MIN_BARS 筆），
    已經補過的下次執行會自動跳過，執行時間會隨著資料逐日累積越來越短，最終
    穩定在只處理新上市或前一天回補失敗的少數幾檔。"""
    cutoff = date.today() - timedelta(days=months * 31 + 10)

    twse_codes = [c for (c,) in db.query(Stock.code).filter(Stock.market == Market.TWSE).all()]
    if not twse_codes:
        return 0

    bar_counts = dict(
        db.query(DailyBar.stock_code, func.count(DailyBar.id))
        .filter(DailyBar.stock_code.in_(twse_codes), DailyBar.trade_date >= cutoff)
        .group_by(DailyBar.stock_code)
        .all()
    )
    targets = [code for code in twse_codes if bar_counts.get(code, 0) < DAILY_BAR_MIN_BARS]
    if not targets:
        logger.info("backfill_all_twse_daily_bars: 全部上市股票資料都已足夠，略過")
        return 0

    logger.info("backfill_all_twse_daily_bars: 需要回補 %d 檔上市股票（分批進行）", len(targets))
    total = 0
    async with httpx.AsyncClient(timeout=15, headers=_HEADERS) as client:
        for i in range(0, len(targets), batch_size):
            batch = targets[i : i + batch_size]
            for code in batch:
                try:
                    total += await backfill_twse_history(db, code, months, client=client)
                except Exception:
                    logger.exception("backfill_all_twse_daily_bars: %s 回補失敗", code)
            if i + batch_size < len(targets):
                await asyncio.sleep(delay_seconds)

    logger.info("backfill_all_twse_daily_bars: 回補完成，處理 %d 檔、寫入 %d 筆日K", len(targets), total)
    return total
