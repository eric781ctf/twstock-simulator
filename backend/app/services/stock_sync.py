import logging

from sqlalchemy.orm import Session

from app.models import DailyBar, Market, Stock, StockValuation
from app.services.twse_client import fetch_listed_stocks, fetch_otc_stocks, fetch_valuations

logger = logging.getLogger(__name__)


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


async def sync_valuations(db: Session) -> int:
    """同步全市場本益比、殖利率、股價淨值比到 stock_valuations，供搜尋頁基本面區塊使用。
    必須在 sync_stocks 之後呼叫，確保 stocks 表已經有對應的股票代碼（外鍵）。"""
    items = await fetch_valuations()
    if not items:
        logger.warning("sync_valuations: 外部 API 無回傳資料，略過本次同步")
        return 0

    known_codes = {c for (c,) in db.query(Stock.code).all()}
    items = [item for item in items if item["code"] in known_codes]

    existing = {
        v.stock_code: v
        for v in db.query(StockValuation).filter(StockValuation.stock_code.in_([i["code"] for i in items])).all()
    }

    count = 0
    for item in items:
        code = item["code"]
        if code in existing:
            v = existing[code]
            v.pe_ratio, v.dividend_yield, v.pb_ratio = item["pe_ratio"], item["dividend_yield"], item["pb_ratio"]
        else:
            db.add(
                StockValuation(
                    stock_code=code,
                    pe_ratio=item["pe_ratio"],
                    dividend_yield=item["dividend_yield"],
                    pb_ratio=item["pb_ratio"],
                )
            )
        count += 1

    db.commit()
    logger.info("sync_valuations: 同步完成，共 %d 檔", count)
    return count
