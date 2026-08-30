from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Account, Position, User
from app.schemas import LeaderboardEntryOut
from app.services.auth import get_current_user
from app.services.twse_client import fetch_quotes

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


@router.get("", response_model=list[LeaderboardEntryOut])
async def get_leaderboard(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    accounts = db.query(Account, User.nickname).join(User, Account.user_id == User.id).all()

    positions = db.query(Position).filter(Position.quantity > 0).all()
    positions_by_account: dict[int, list[Position]] = defaultdict(list)
    for p in positions:
        positions_by_account[p.account_id].append(p)

    codes_with_market = {(p.stock_code, p.stock.market.value) for p in positions}
    quotes = await fetch_quotes(list(codes_with_market))

    entries = []
    for account, nickname in accounts:
        market_value = 0.0
        for p in positions_by_account.get(account.id, []):
            quote = quotes.get(p.stock_code)
            price = quote["price"] if quote and quote["price"] is not None else float(p.avg_cost)
            market_value += price * p.quantity

        cash_balance = float(account.cash_balance)
        entries.append(
            LeaderboardEntryOut(
                nickname=nickname,
                total_assets=cash_balance + market_value,
                cash_balance=cash_balance,
                market_value=market_value,
            )
        )

    entries.sort(key=lambda e: e.total_assets, reverse=True)
    return entries
