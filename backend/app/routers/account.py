from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EquitySnapshot, Position, User
from app.schemas import AccountOut, EquitySnapshotOut
from app.services.auth import get_current_user
from app.services.matching import get_account_for_user
from app.services.quote_cache import get_quotes_cached

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=AccountOut)
def get_account(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    return AccountOut(
        id=account.id,
        name=account.name,
        cash_balance=float(account.cash_balance),
        frozen_cash=float(account.frozen_cash),
        available_cash=float(account.cash_balance) - float(account.frozen_cash),
    )


@router.get("/equity-history", response_model=list[EquitySnapshotOut])
async def get_equity_history(
    days: int = 180, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    account = get_account_for_user(db, current_user.id)
    cutoff = date.today() - timedelta(days=days)
    snapshots = (
        db.query(EquitySnapshot)
        .filter(
            EquitySnapshot.account_id == account.id,
            EquitySnapshot.snapshot_date >= cutoff,
            EquitySnapshot.snapshot_date < date.today(),
        )
        .order_by(EquitySnapshot.snapshot_date.asc())
        .all()
    )
    result = [
        EquitySnapshotOut(
            snapshot_date=s.snapshot_date.isoformat(),
            cash_balance=float(s.cash_balance),
            market_value=float(s.market_value),
            total_assets=float(s.total_assets),
        )
        for s in snapshots
    ]

    # 每日排程只寫到「昨天」（今天的收盤價要等明天早上才會同步進來），這裡
    # 補上「今天」這一筆即時資料，走勢圖才不會停在昨天。跟市價單共用同一份
    # quote_cache，不會為了這張圖多打報價 API。
    positions = db.query(Position).filter(Position.account_id == account.id, Position.quantity > 0).all()
    market_value_today = 0.0
    if positions:
        codes_with_market = [(p.stock_code, p.stock.market.value) for p in positions]
        quotes = await get_quotes_cached(codes_with_market)
        for p in positions:
            quote = quotes.get(p.stock_code)
            price = quote["price"] if quote and quote["price"] is not None else float(p.avg_cost)
            market_value_today += price * p.quantity

    cash_today = float(account.cash_balance)
    result.append(
        EquitySnapshotOut(
            snapshot_date=date.today().isoformat(),
            cash_balance=cash_today,
            market_value=market_value_today,
            total_assets=cash_today + market_value_today,
        )
    )
    return result
