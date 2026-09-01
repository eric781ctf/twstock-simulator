"""策略引擎：每分鐘跑一次（見 scheduler.py），對每組啟用中的策略做買進掃描
與賣出檢查。買進條件掃描「本地日K資料足夠」的整個市場（不限自選股），賣出
條件套用在該帳戶目前的所有持股上。

效能設計：均線/KD/連續漲跌都是純粹從 daily_bars 算出來的日線指標，daily_bars
本身已經由每日排程（stock_sync.sync_stocks）幫全市場（上市+上櫃、上萬檔）
每天累積一筆，跟自選股、持股都無關——所以整個市場的掃描不需要另外打即時報價
API，只有最後真的要下單的少數幾檔才需要即時報價。這也是為什麼可以做到「掃全
市場」而不會撞到 mis.twse 的即時報價 3 req/5s 限制。

condition 是「日線」等級的訊號，一天只會變一次（收盤才會有新的一筆 daily_bar），
所以每分鐘重跑不會一直找到新訊號——真正的作用是讓「剛啟用的策略」或「今天
新同步進來的資料」能在一分鐘內被反應到，而不是要等到隔天。同一檔股票、同一
個方向，一組策略一天只會真的下單一次（見 StrategyTrade 的 unique constraint）。"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Account, DailyBar, Position, Side, Stock, Strategy, StrategyTrade
from app.services.feature_flags import STRATEGY, is_enabled
from app.services.indicators import compute_rank_value
from app.services.matching import TAIPEI_TZ, OrderValidationError, create_order, is_after_hours_window, is_trading_hours
from app.services.strategy_conditions import evaluate_all

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 130  # 足夠湊出 60 個交易日（含假日緩衝），MA60/KD 都夠用
MIN_BARS_REQUIRED = 15  # 太短的資料連基本的 KD/連續天數都算不準，直接跳過


def _load_bars_by_code(db: Session) -> dict[str, list[DailyBar]]:
    cutoff = date.today() - timedelta(days=LOOKBACK_DAYS)
    rows = (
        db.query(DailyBar)
        .filter(DailyBar.trade_date >= cutoff)
        .order_by(DailyBar.stock_code.asc(), DailyBar.trade_date.asc())
        .all()
    )
    by_code: dict[str, list[DailyBar]] = {}
    for row in rows:
        by_code.setdefault(row.stock_code, []).append(row)
    return by_code


def _already_traded_today(db: Session, strategy_id: int, stock_code: str, side: Side, today: date) -> bool:
    return (
        db.query(StrategyTrade)
        .filter(
            StrategyTrade.strategy_id == strategy_id,
            StrategyTrade.stock_code == stock_code,
            StrategyTrade.side == side,
            StrategyTrade.trade_date == today,
        )
        .first()
        is not None
    )


def _log_strategy_trade(db: Session, strategy_id: int, stock_code: str, side: Side, today: date, order_id: int) -> None:
    db.add(StrategyTrade(strategy_id=strategy_id, stock_code=stock_code, side=side, trade_date=today, order_id=order_id))
    db.commit()


async def _run_sell_pass(db: Session, strategy: Strategy, account: Account, bars_by_code: dict, today: date) -> None:
    positions = db.query(Position).filter(Position.account_id == account.id, Position.quantity > 0).all()
    for position in positions:
        bars = bars_by_code.get(position.stock_code)
        if not bars or len(bars) < MIN_BARS_REQUIRED:
            continue
        if _already_traded_today(db, strategy.id, position.stock_code, Side.SELL, today):
            continue
        if not evaluate_all(strategy.sell_conditions, bars):
            continue

        stock = db.get(Stock, position.stock_code)
        available_qty = position.quantity - position.frozen_quantity
        if available_qty <= 0:
            continue
        sell_qty = min(strategy.quantity, available_qty)
        try:
            order = await create_order(db, account, stock, Side.SELL, "market", None, None, sell_qty)
            _log_strategy_trade(db, strategy.id, position.stock_code, Side.SELL, today, order.id)
            logger.info("策略 %s 自動賣出 %s x%d", strategy.name, position.stock_code, sell_qty)
        except OrderValidationError as e:
            logger.debug("策略 %s 賣出 %s 失敗：%s", strategy.name, position.stock_code, e)


async def _run_buy_pass(db: Session, strategy: Strategy, account: Account, bars_by_code: dict, today: date) -> None:
    if not strategy.buy_conditions:
        return

    held_codes = {p.stock_code for p in db.query(Position).filter(Position.account_id == account.id, Position.quantity > 0).all()}

    candidates: list[tuple[str, float]] = []
    for stock_code, bars in bars_by_code.items():
        if stock_code in held_codes or len(bars) < MIN_BARS_REQUIRED:
            continue
        if _already_traded_today(db, strategy.id, stock_code, Side.BUY, today):
            continue
        if not evaluate_all(strategy.buy_conditions, bars):
            continue
        rank_value = compute_rank_value(strategy.rank_by, bars)
        if rank_value is None:
            continue
        candidates.append((stock_code, rank_value))

    if not candidates:
        return

    candidates.sort(key=lambda item: item[1], reverse=(strategy.rank_direction == "desc"))
    top_codes = [code for code, _ in candidates[: strategy.top_n]]

    for stock_code in top_codes:
        stock = db.get(Stock, stock_code)
        if not stock:
            continue
        try:
            order = await create_order(db, account, stock, Side.BUY, "market", None, None, strategy.quantity)
            _log_strategy_trade(db, strategy.id, stock_code, Side.BUY, today, order.id)
            logger.info("策略 %s 自動買進 %s x%d", strategy.name, stock_code, strategy.quantity)
        except OrderValidationError as e:
            logger.debug("策略 %s 買進 %s 失敗：%s", strategy.name, stock_code, e)


async def run_strategy_cycle(db: Session) -> None:
    if not is_enabled(db, STRATEGY):
        return
    if not (is_trading_hours() or is_after_hours_window()):
        return

    active_strategies = db.query(Strategy).filter(Strategy.is_active.is_(True)).all()
    if not active_strategies:
        return

    today = datetime.now(TAIPEI_TZ).date()
    bars_by_code = _load_bars_by_code(db)

    for strategy in active_strategies:
        account = db.get(Account, strategy.account_id)
        if account is None:
            continue
        try:
            await _run_sell_pass(db, strategy, account, bars_by_code, today)
            await _run_buy_pass(db, strategy, account, bars_by_code, today)
        except Exception:
            logger.exception("策略 %s (id=%d) 執行時發生錯誤", strategy.name, strategy.id)
