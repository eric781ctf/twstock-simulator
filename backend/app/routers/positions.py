from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Position, User
from app.schemas import PositionOut
from app.services.auth import get_current_user
from app.services.matching import get_account_for_user
from app.services.twse_client import fetch_quotes

router = APIRouter(prefix="/positions", tags=["positions"])


@router.get("", response_model=list[PositionOut])
async def list_positions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    positions = (
        db.query(Position)
        .filter(Position.account_id == account.id, Position.quantity > 0)
        .all()
    )
    if not positions:
        return []

    codes_with_market = [(p.stock_code, p.stock.market.value) for p in positions]
    quotes = await fetch_quotes(codes_with_market)

    result = []
    for p in positions:
        quote = quotes.get(p.stock_code)
        current_price = quote["price"] if quote else None
        market_value = current_price * p.quantity if current_price is not None else None
        unrealized_pnl = (
            (current_price - float(p.avg_cost)) * p.quantity if current_price is not None else None
        )
        result.append(
            PositionOut(
                stock_code=p.stock_code,
                stock_name=p.stock.name,
                quantity=p.quantity,
                frozen_quantity=p.frozen_quantity,
                avg_cost=float(p.avg_cost),
                current_price=current_price,
                market_value=market_value,
                unrealized_pnl=unrealized_pnl,
            )
        )
    return result
