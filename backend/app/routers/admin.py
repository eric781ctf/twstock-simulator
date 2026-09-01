from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import AdminAmountIn, AdminAccountOut, DefaultInitialCashOut
from app.services.admin import AdminActionError, add_cash_to_all, delete_account, freeze_account, list_all_accounts
from app.services.app_config import get_default_initial_cash, set_default_initial_cash
from app.services.auth import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/accounts", response_model=list[AdminAccountOut])
def get_accounts(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = list_all_accounts(db)
    return [
        AdminAccountOut(
            user_id=user.id,
            username=user.username,
            nickname=user.nickname,
            is_admin=user.is_admin,
            cash_balance=float(account.cash_balance) if account else None,
            frozen_cash=float(account.frozen_cash) if account else None,
            frozen_until=user.frozen_until,
            created_at=user.created_at,
        )
        for user, account in rows
    ]


@router.get("/settings/default-initial-cash", response_model=DefaultInitialCashOut)
def get_default_cash(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return DefaultInitialCashOut(amount=get_default_initial_cash(db))


@router.post("/settings/default-initial-cash", response_model=DefaultInitialCashOut)
def update_default_cash(payload: AdminAmountIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    amount = set_default_initial_cash(db, payload.amount)
    return DefaultInitialCashOut(amount=amount)


@router.post("/accounts/add-cash")
def add_cash(payload: AdminAmountIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    count = add_cash_to_all(db, payload.amount)
    return {"updated": count}


@router.delete("/accounts/{user_id}")
def remove_account(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    try:
        delete_account(db, user_id)
    except AdminActionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"deleted": True}


@router.post("/accounts/{user_id}/freeze")
def freeze(user_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    try:
        frozen_until = freeze_account(db, user_id)
    except AdminActionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"frozen_until": frozen_until}
