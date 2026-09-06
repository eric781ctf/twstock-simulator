from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Order, Strategy, StrategyTrade, User
from app.schemas import BacktestRequest, BacktestResultOut, StrategyCreate, StrategyOut, StrategyTradeOut
from app.services.auth import get_current_user
from app.services.backtest import BacktestError, run_backtest
from app.services.feature_flags import STRATEGY, is_enabled
from app.services.matching import get_account_for_user
from app.services.strategy_conditions import ConditionValidationError, validate_conditions


def require_strategy_enabled(db: Session = Depends(get_db)) -> None:
    if not is_enabled(db, STRATEGY):
        raise HTTPException(status_code=503, detail="策略功能維護中")


router = APIRouter(prefix="/strategies", tags=["strategies"], dependencies=[Depends(require_strategy_enabled)])


def _validate_payload(payload: StrategyCreate) -> None:
    try:
        validate_conditions(payload.buy_conditions)
        validate_conditions(payload.sell_conditions)
    except ConditionValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not payload.buy_conditions and not payload.sell_conditions:
        raise HTTPException(status_code=422, detail="至少要設定一個買進或賣出條件")


@router.get("", response_model=list[StrategyOut])
def list_strategies(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    return db.query(Strategy).filter(Strategy.account_id == account.id).order_by(Strategy.created_at.desc()).all()


@router.post("", response_model=StrategyOut, status_code=201)
def create_strategy(payload: StrategyCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    _validate_payload(payload)

    strategy = Strategy(
        account_id=account.id,
        name=payload.name,
        quantity=payload.quantity,
        buy_conditions=payload.buy_conditions,
        sell_conditions=payload.sell_conditions,
        rank_by=payload.rank_by,
        rank_direction=payload.rank_direction,
        top_n=payload.top_n,
        is_active=False,
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return strategy


def _get_owned_strategy(db: Session, account_id: int, strategy_id: int) -> Strategy:
    strategy = db.get(Strategy, strategy_id)
    if not strategy or strategy.account_id != account_id:
        raise HTTPException(status_code=404, detail="策略不存在")
    return strategy


@router.put("/{strategy_id}", response_model=StrategyOut)
def update_strategy(
    strategy_id: int,
    payload: StrategyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = get_account_for_user(db, current_user.id)
    strategy = _get_owned_strategy(db, account.id, strategy_id)
    _validate_payload(payload)

    strategy.name = payload.name
    strategy.quantity = payload.quantity
    strategy.buy_conditions = payload.buy_conditions
    strategy.sell_conditions = payload.sell_conditions
    strategy.rank_by = payload.rank_by
    strategy.rank_direction = payload.rank_direction
    strategy.top_n = payload.top_n
    db.commit()
    db.refresh(strategy)
    return strategy


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    strategy = _get_owned_strategy(db, account.id, strategy_id)
    db.query(StrategyTrade).filter(StrategyTrade.strategy_id == strategy.id).delete(synchronize_session=False)
    db.delete(strategy)
    db.commit()
    return {"deleted": True}


@router.post("/{strategy_id}/activate", response_model=StrategyOut)
def activate_strategy(strategy_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    strategy = _get_owned_strategy(db, account.id, strategy_id)

    db.query(Strategy).filter(Strategy.account_id == account.id, Strategy.id != strategy.id).update({"is_active": False})
    strategy.is_active = True
    db.commit()
    db.refresh(strategy)
    return strategy


@router.post("/{strategy_id}/deactivate", response_model=StrategyOut)
def deactivate_strategy(strategy_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    strategy = _get_owned_strategy(db, account.id, strategy_id)
    strategy.is_active = False
    db.commit()
    db.refresh(strategy)
    return strategy


@router.post("/{strategy_id}/backtest", response_model=BacktestResultOut)
def backtest_strategy(
    strategy_id: int,
    payload: BacktestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    account = get_account_for_user(db, current_user.id)
    strategy = _get_owned_strategy(db, account.id, strategy_id)
    try:
        result = run_backtest(db, strategy, payload.start_date, payload.end_date, payload.initial_cash)
    except BacktestError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result


@router.get("/{strategy_id}/trades", response_model=list[StrategyTradeOut])
def get_strategy_trades(strategy_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    account = get_account_for_user(db, current_user.id)
    strategy = _get_owned_strategy(db, account.id, strategy_id)

    rows = (
        db.query(StrategyTrade)
        .filter(StrategyTrade.strategy_id == strategy.id)
        .order_by(StrategyTrade.created_at.desc())
        .all()
    )
    result = []
    for row in rows:
        order = db.get(Order, row.order_id) if row.order_id else None
        result.append(
            StrategyTradeOut(
                id=row.id,
                stock_code=row.stock_code,
                stock_name=row.stock.name if row.stock else row.stock_code,
                side=row.side,
                trade_date=row.trade_date.isoformat(),
                price=float(order.filled_price) if order and order.filled_price is not None else None,
                quantity=order.quantity if order else None,
                status=order.status if order else None,
            )
        )
    return result
