from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import AccountOut
from app.services.auth import get_current_user
from app.services.matching import get_account_for_user

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
