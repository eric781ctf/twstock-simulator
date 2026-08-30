from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PricePoint, Stock, StockValuationHistory
from app.schemas import FundamentalsOut
from app.services.history import get_daily_history
from app.services.matching import TAIPEI_TZ

router = APIRouter(prefix="/stocks", tags=["market-data"])


class DailyBarOut(BaseModel):
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class PricePointOut(BaseModel):
    ts: str
    price: float


@router.get("/{code}/daily-history", response_model=list[DailyBarOut])
async def daily_history(code: str, months: int = 3, db: Session = Depends(get_db)):
    stock = db.get(Stock, code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    bars = await get_daily_history(db, stock, months=months)
    return [
        DailyBarOut(trade_date=b.trade_date, open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume)
        for b in bars
    ]


@router.get("/{code}/intraday", response_model=list[PricePointOut])
def intraday(code: str, db: Session = Depends(get_db)):
    stock = db.get(Stock, code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    now = datetime.now(TAIPEI_TZ)
    day_start = datetime.combine(now.date(), time.min, tzinfo=TAIPEI_TZ)
    day_end = datetime.combine(now.date(), time.max, tzinfo=TAIPEI_TZ)

    points = (
        db.query(PricePoint)
        .filter(PricePoint.stock_code == code, PricePoint.ts >= day_start, PricePoint.ts <= day_end)
        .order_by(PricePoint.ts.asc())
        .all()
    )
    return [PricePointOut(ts=p.ts.isoformat(), price=p.price) for p in points]


class FundamentalsHistoryPointOut(BaseModel):
    as_of_date: date
    pe_ratio: float | None
    dividend_yield: float | None
    pb_ratio: float | None


@router.get("/{code}/fundamentals", response_model=FundamentalsOut)
def fundamentals(code: str, db: Session = Depends(get_db)):
    stock = db.get(Stock, code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    v = (
        db.query(StockValuationHistory)
        .filter(StockValuationHistory.stock_code == code)
        .order_by(StockValuationHistory.as_of_date.desc())
        .first()
    )
    if not v:
        return FundamentalsOut(stock_code=code, pe_ratio=None, dividend_yield=None, pb_ratio=None, updated_at=None)

    return FundamentalsOut(
        stock_code=code,
        pe_ratio=v.pe_ratio,
        dividend_yield=v.dividend_yield,
        pb_ratio=v.pb_ratio,
        updated_at=datetime.combine(v.as_of_date, time.min, tzinfo=TAIPEI_TZ),
    )


@router.get("/{code}/fundamentals-history", response_model=list[FundamentalsHistoryPointOut])
def fundamentals_history(code: str, years: int = 3, db: Session = Depends(get_db)):
    stock = db.get(Stock, code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    cutoff = date.today() - timedelta(days=years * 365)
    rows = (
        db.query(StockValuationHistory)
        .filter(StockValuationHistory.stock_code == code, StockValuationHistory.as_of_date >= cutoff)
        .order_by(StockValuationHistory.as_of_date.asc())
        .all()
    )
    return [
        FundamentalsHistoryPointOut(
            as_of_date=r.as_of_date, pe_ratio=r.pe_ratio, dividend_yield=r.dividend_yield, pb_ratio=r.pb_ratio
        )
        for r in rows
    ]
