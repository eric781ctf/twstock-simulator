from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    AdminAccountOut,
    AdminAmountIn,
    DailyBarStatsOut,
    DefaultInitialCashOut,
    FeatureFlagOut,
    FeatureFlagUpdateIn,
)
from app.services.admin import AdminActionError, add_cash_to_all, delete_account, freeze_account, list_all_accounts
from app.services.app_config import get_default_initial_cash, set_default_initial_cash
from app.services.auth import require_admin
from app.services.feature_flags import FLAG_LABELS, get_all_flags, set_flag
from app.services.stock_sync import get_daily_bar_stats

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


@router.get("/daily-bar-stats", response_model=DailyBarStatsOut)
def get_daily_bar_stats_endpoint(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    stats = get_daily_bar_stats(db)
    return DailyBarStatsOut(**stats)


@router.get("/feature-flags", response_model=list[FeatureFlagOut])
def list_feature_flags(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return get_all_flags(db)


@router.post("/feature-flags/{key}", response_model=FeatureFlagOut)
def update_feature_flag(
    key: str, payload: FeatureFlagUpdateIn, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    try:
        enabled = set_flag(db, key, payload.enabled)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return FeatureFlagOut(key=key, label=FLAG_LABELS[key], enabled=enabled)
