from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Stock
from app.schemas import QuoteOut, StockOut
from app.services.twse_client import fetch_quotes

router = APIRouter(prefix="/stocks", tags=["stocks"])


@router.get("", response_model=list[StockOut])
def search_stocks(query: str = "", limit: int = 20, db: Session = Depends(get_db)):
    q = db.query(Stock)
    if query:
        like = f"%{query}%"
        q = q.filter(or_(Stock.code.ilike(like), Stock.name.ilike(like)))
    return q.order_by(Stock.code).limit(limit).all()


@router.get("/{code}/quote", response_model=QuoteOut)
async def get_quote(code: str, db: Session = Depends(get_db)):
    stock = db.get(Stock, code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    quotes = await fetch_quotes([(stock.code, stock.market.value)])
    quote = quotes.get(stock.code)
    if not quote:
        return QuoteOut(code=stock.code, name=stock.name, price=None, prev_close=None, is_stale=True)

    return QuoteOut(
        code=stock.code,
        name=stock.name,
        price=quote["price"],
        prev_close=quote["prev_close"],
        open=quote.get("open"),
        high=quote.get("high"),
        low=quote.get("low"),
        is_stale=quote["price"] is None,
    )
