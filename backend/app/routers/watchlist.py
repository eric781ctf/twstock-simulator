from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Stock, User, WatchlistItem
from app.schemas import WatchlistCreate, WatchlistItemOut
from app.services.auth import get_current_user
from app.services.matching import get_account_for_user
from app.services.twse_client import fetch_quotes

router = APIRouter(prefix="/watchlist", tags=["watchlist"])

MAX_WATCHLIST_SIZE = 20


@router.get("", response_model=list[WatchlistItemOut])
async def list_watchlist(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.account_id == account.id)
        .order_by(WatchlistItem.created_at.asc())
        .all()
    )
    if not items:
        return []

    codes_with_market = [(item.stock_code, item.stock.market.value) for item in items]
    quotes = await fetch_quotes(codes_with_market)

    return [
        WatchlistItemOut(
            stock_code=item.stock_code,
            stock_name=item.stock.name,
            market=item.stock.market,
            created_at=item.created_at,
            current_price=(quotes.get(item.stock_code) or {}).get("price"),
        )
        for item in items
    ]


@router.post("", response_model=WatchlistItemOut, status_code=201)
def add_watchlist_item(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = get_account_for_user(db, current_user.id)
    stock = db.get(Stock, payload.stock_code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    existing = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.account_id == account.id, WatchlistItem.stock_code == stock.code)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="這檔股票已經在自選股清單中")

    count = db.query(WatchlistItem).filter(WatchlistItem.account_id == account.id).count()
    if count >= MAX_WATCHLIST_SIZE:
        raise HTTPException(status_code=400, detail=f"自選股清單最多只能加入 {MAX_WATCHLIST_SIZE} 檔股票")

    item = WatchlistItem(account_id=account.id, stock_code=stock.code)
    db.add(item)
    db.commit()
    db.refresh(item)
    return WatchlistItemOut(
        stock_code=item.stock_code, stock_name=stock.name, market=stock.market, created_at=item.created_at
    )


@router.delete("/{stock_code}", status_code=204)
def remove_watchlist_item(
    stock_code: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = get_account_for_user(db, current_user.id)
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.account_id == account.id, WatchlistItem.stock_code == stock_code)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="自選股清單中沒有這檔股票")
    db.delete(item)
    db.commit()
