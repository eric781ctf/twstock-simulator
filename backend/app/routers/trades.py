from datetime import date, datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Trade, User
from app.schemas import TradeOut
from app.services.auth import get_current_user
from app.services.matching import TAIPEI_TZ, get_account_for_user

router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("", response_model=list[TradeOut])
def list_trades(
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = get_account_for_user(db, current_user.id)
    q = db.query(Trade).filter(Trade.account_id == account.id)
    if start_date:
        q = q.filter(Trade.executed_at >= datetime.combine(start_date, time.min, tzinfo=TAIPEI_TZ))
    if end_date:
        q = q.filter(Trade.executed_at <= datetime.combine(end_date, time.max, tzinfo=TAIPEI_TZ))
    return q.order_by(Trade.executed_at.desc()).all()
