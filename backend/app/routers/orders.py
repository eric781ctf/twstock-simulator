from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, OrderStatus, Stock, User
from app.schemas import OrderCreate, OrderOut
from app.services.auth import get_current_user
from app.services.matching import TAIPEI_TZ, OrderValidationError, cancel_order, create_order, get_account_for_user

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=OrderOut, status_code=201)
async def place_order(
    payload: OrderCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    account = get_account_for_user(db, current_user.id)
    stock = db.get(Stock, payload.stock_code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票代碼不存在")

    try:
        order = await create_order(
            db, account, stock, payload.side, payload.order_type, payload.price, payload.stop_price, payload.quantity
        )
    except OrderValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return order


@router.get("", response_model=list[OrderOut])
def list_orders(
    status: OrderStatus | None = None,
    today_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = get_account_for_user(db, current_user.id)
    q = db.query(Order).filter(Order.account_id == account.id)
    if status:
        q = q.filter(Order.status == status)
    if today_only:
        today_start = datetime.combine(datetime.now(TAIPEI_TZ).date(), time.min, tzinfo=TAIPEI_TZ)
        # 委託回報（pending）依下單時間篩選；成交回報（filled）依實際成交時間篩選，
        # 這樣「今天下單、隔天才成交」的極端情況也能落在正確的分類。
        if status == OrderStatus.FILLED:
            q = q.filter(Order.filled_at >= today_start)
        else:
            q = q.filter(Order.created_at >= today_start)
    return q.order_by(Order.created_at.desc()).all()


@router.delete("/{order_id}", response_model=OrderOut)
def cancel(order_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    order = db.get(Order, order_id)
    if not order or order.account_id != account.id:
        raise HTTPException(status_code=404, detail="訂單不存在")
    try:
        order = cancel_order(db, order)
    except OrderValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return order
