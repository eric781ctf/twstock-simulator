import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import User
from app.schemas import (
    AdminAccountOut,
    AdminAmountIn,
    BackfillProgressOut,
    BackfillStatusOut,
    BackfillTargetIn,
    DailyBarStatsOut,
    DefaultInitialCashOut,
    FeatureFlagOut,
    FeatureFlagUpdateIn,
    SchedulerFlagOut,
)
from app.services import backfill_status
from app.services.admin import AdminActionError, add_cash_to_all, delete_account, freeze_account, list_all_accounts
from app.services.app_config import (
    get_default_initial_cash,
    get_target_backfill_months,
    set_default_initial_cash,
    set_target_backfill_months,
)
from app.services.auth import require_admin
from app.services.feature_flags import FLAG_LABELS, get_all_flags, get_model_system_flags, set_flag
from app.services.stock_sync import backfill_twse_daily_bars_by_date, get_daily_bar_stats, get_twse_earliest_bar_date

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


async def _run_backfill_task(months: int) -> None:
    """admin 手動觸發的回補，走「逐日抓全市場」而不是「逐檔抓歷史」。

    同樣補 N 個月，逐日只要每個交易日一次請求（6 個月約 120 次），逐檔則要
    1380 檔 × N 個月（約 8000 次）。少打 98% 的請求，速度快得多，也不會一直
    去撞 TWSE 的限流。"""
    db = SessionLocal()
    try:
        end = date.today()
        start = end - timedelta(days=months * 31)
        await backfill_twse_daily_bars_by_date(db, start, end)
    except Exception:
        logger.exception("手動觸發的日K回補發生錯誤")
    finally:
        db.close()


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


def _backfill_status_out(db: Session, months: int | None = None) -> BackfillStatusOut:
    return BackfillStatusOut(
        earliest_date=get_twse_earliest_bar_date(db),
        target_months=months if months is not None else get_target_backfill_months(db),
        progress=BackfillProgressOut(**backfill_status.snapshot()),
    )


@router.get("/models/backfill-status", response_model=BackfillStatusOut)
def get_backfill_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _backfill_status_out(db)


@router.post("/models/backfill", response_model=BackfillStatusOut)
async def trigger_backfill(payload: BackfillTargetIn, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    # 同時跑兩輪只會讓對 TWSE 的請求密度加倍，正好是節流想避免的事
    if backfill_status.is_active():
        raise HTTPException(status_code=409, detail="已經有一輪回補正在進行中，請等它跑完再調整目標月數")

    months = set_target_backfill_months(db, payload.target_months)
    asyncio.create_task(_run_backfill_task(months))
    return _backfill_status_out(db, months)


@router.get("/models/schedulers", response_model=list[SchedulerFlagOut])
def list_model_schedulers(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """只回傳跟預測模型系統有關的排程開關。切換沿用下面的 feature-flags 端點。"""
    return [SchedulerFlagOut(**flag) for flag in get_model_system_flags(db)]


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
