import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, Order, OrderStatus, Position, PricePoint, Side, Stock, Trade, WatchlistItem
from app.services.fees import compute_amount, compute_commission, compute_tax
from app.services.twse_client import fetch_quotes

logger = logging.getLogger(__name__)

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


TRADING_START = _parse_hhmm(settings.trading_start)
TRADING_END = _parse_hhmm(settings.trading_end)
AFTER_HOURS_END = _parse_hhmm(settings.after_hours_end)


def is_trading_hours(now: datetime | None = None) -> bool:
    now = now or datetime.now(TAIPEI_TZ)
    if now.weekday() >= 5:  # 週六、週日
        return False
    return TRADING_START <= now.time() <= TRADING_END


def is_after_hours_window(now: datetime | None = None) -> bool:
    """模擬盤後定價交易：收盤後到 AFTER_HOURS_END 這段時間都能用「收盤價」買進或賣出，
    只在平日（週一到五）才有效——週末股市本來就沒開盤，不算盤後。"""
    now = now or datetime.now(TAIPEI_TZ)
    if now.weekday() >= 5:  # 週六、週日沒有開盤，也就沒有盤後
        return False
    return TRADING_END < now.time() <= AFTER_HOURS_END


def create_account_for_user(db: Session, user_id: int) -> Account:
    account = Account(user_id=user_id, name="我的帳戶", cash_balance=settings.initial_cash, frozen_cash=0)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def get_account_for_user(db: Session, user_id: int) -> Account:
    account = db.query(Account).filter(Account.user_id == user_id).first()
    if account is None:
        raise OrderValidationError("帳戶不存在")
    return account


def _get_or_create_position(db: Session, account_id: int, stock_code: str) -> Position:
    position = (
        db.query(Position)
        .filter(Position.account_id == account_id, Position.stock_code == stock_code)
        .first()
    )
    if position is None:
        position = Position(account_id=account_id, stock_code=stock_code, quantity=0, frozen_quantity=0, avg_cost=0)
        db.add(position)
        db.flush()
    return position


class OrderValidationError(Exception):
    pass


async def create_order(db: Session, account: Account, stock: Stock, side: Side, price: float, quantity: int) -> Order:
    now = datetime.now(TAIPEI_TZ)
    trading = is_trading_hours(now)
    after_hours = not trading and is_after_hours_window(now)

    if not trading and not after_hours:
        raise OrderValidationError("目前非可下單時段（盤中或盤後至 24:00 前才能下單）")

    if after_hours:
        # 盤後只能用「收盤價」成交，不是使用者自訂的限價；此時 mis.twse 的報價已經停在
        # 當天最後一筆成交價，等同收盤價，直接拿來當成交價使用並立刻成交。
        quote = await fetch_quotes([(stock.code, stock.market.value)])
        q = quote.get(stock.code)
        if not q or q["price"] is None:
            raise OrderValidationError("目前無法取得今日收盤價，請稍後再試")
        price = q["price"]

    if side == Side.BUY:
        amount = compute_amount(price, quantity)
        estimated_fee = compute_commission(amount)
        required = amount + estimated_fee
        available_cash = float(account.cash_balance) - float(account.frozen_cash)
        if available_cash < required:
            raise OrderValidationError(f"可用資金不足，需要 {required}，可用 {available_cash}")
        account.frozen_cash = float(account.frozen_cash) + required
        order = Order(
            account_id=account.id,
            stock_code=stock.code,
            side=side,
            price=price,
            quantity=quantity,
            status=OrderStatus.PENDING,
            reserved_amount=required,
        )
    else:
        position = _get_or_create_position(db, account.id, stock.code)
        available_qty = position.quantity - position.frozen_quantity
        if available_qty < quantity:
            raise OrderValidationError(f"庫存不足，需要 {quantity} 股，可用 {available_qty} 股")
        position.frozen_quantity += quantity
        order = Order(
            account_id=account.id,
            stock_code=stock.code,
            side=side,
            price=price,
            quantity=quantity,
            status=OrderStatus.PENDING,
        )

    db.add(order)
    db.flush()

    if after_hours:
        _fill_order(db, order, price)

    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order: Order) -> Order:
    if order.status != OrderStatus.PENDING:
        raise OrderValidationError("只能取消尚未成交的掛單")
    _release_reservation(db, order)
    order.status = OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)
    return order


def _release_reservation(db: Session, order: Order) -> None:
    account = db.get(Account, order.account_id)
    if order.side == Side.BUY:
        account.frozen_cash = float(account.frozen_cash) - float(order.reserved_amount or 0)
    else:
        position = _get_or_create_position(db, order.account_id, order.stock_code)
        position.frozen_quantity = max(0, position.frozen_quantity - order.quantity)


def _fill_order(db: Session, order: Order, fill_price: float) -> None:
    account = db.get(Account, order.account_id)
    position = _get_or_create_position(db, order.account_id, order.stock_code)
    amount = compute_amount(fill_price, order.quantity)
    fee = compute_commission(amount)

    if order.side == Side.BUY:
        tax = 0.0
        total_cost = amount + fee
        account.frozen_cash = float(account.frozen_cash) - float(order.reserved_amount or 0)
        account.cash_balance = float(account.cash_balance) - total_cost

        new_quantity = position.quantity + order.quantity
        new_total_cost = float(position.avg_cost) * position.quantity + total_cost
        position.avg_cost = (new_total_cost / new_quantity) if new_quantity else 0
        position.quantity = new_quantity
    else:
        tax = compute_tax(amount)
        net_proceeds = amount - fee - tax
        account.cash_balance = float(account.cash_balance) + net_proceeds

        position.frozen_quantity = max(0, position.frozen_quantity - order.quantity)
        position.quantity -= order.quantity
        if position.quantity <= 0:
            position.quantity = 0
            position.avg_cost = 0

    order.status = OrderStatus.FILLED
    order.filled_price = fill_price
    order.filled_at = datetime.now(TAIPEI_TZ)

    trade = Trade(
        order_id=order.id,
        account_id=order.account_id,
        stock_code=order.stock_code,
        side=order.side,
        price=fill_price,
        quantity=order.quantity,
        amount=amount,
        fee=fee,
        tax=tax,
    )
    db.add(trade)


def expire_stale_orders(db: Session) -> int:
    """收盤後（或非當日）仍未成交的掛單一律失效並解凍資金/庫存。"""
    now = datetime.now(TAIPEI_TZ)
    today = now.date()
    is_after_close = now.time() > TRADING_END

    pending_orders = db.query(Order).filter(Order.status == OrderStatus.PENDING).all()
    expired_count = 0
    for order in pending_orders:
        order_date = order.created_at.astimezone(TAIPEI_TZ).date() if order.created_at.tzinfo else order.created_at.date()
        stale = order_date < today or (order_date == today and is_after_close)
        if stale:
            _release_reservation(db, order)
            order.status = OrderStatus.EXPIRED
            expired_count += 1

    if expired_count:
        db.commit()
        logger.info("expire_stale_orders: %d 筆掛單已失效", expired_count)
    return expired_count


async def run_matching_cycle(db: Session) -> int:
    """輪詢所有掛單 + 所有使用者持股 + 所有使用者自選股的最新報價：掛單觸價即成交，
    持股與自選股的價格同時記錄成 PricePoint（給首頁盤中走勢圖用）。合併成單一批次
    報價請求以節省外部 API 額度。回傳成交筆數。"""
    pending_orders = db.query(Order).filter(Order.status == OrderStatus.PENDING).all()
    held_positions = db.query(Position).filter(Position.quantity > 0).all()
    watchlist_items = db.query(WatchlistItem).all()

    if not pending_orders and not held_positions and not watchlist_items:
        return 0

    codes_with_market: dict[str, str] = {}
    for order in pending_orders:
        codes_with_market.setdefault(order.stock_code, order.stock.market.value)
    for position in held_positions:
        codes_with_market.setdefault(position.stock_code, position.stock.market.value)
    for item in watchlist_items:
        codes_with_market.setdefault(item.stock_code, item.stock.market.value)

    quotes = await fetch_quotes(list(codes_with_market.items()))

    filled_count = 0
    for order in pending_orders:
        quote = quotes.get(order.stock_code)
        if not quote or quote["price"] is None:
            continue
        market_price = quote["price"]

        if order.side == Side.BUY and market_price <= float(order.price):
            _fill_order(db, order, market_price)
            filled_count += 1
        elif order.side == Side.SELL and market_price >= float(order.price):
            _fill_order(db, order, market_price)
            filled_count += 1

    tracked_codes = {p.stock_code for p in held_positions} | {w.stock_code for w in watchlist_items}
    for code in tracked_codes:
        quote = quotes.get(code)
        if quote and quote["price"] is not None:
            db.add(PricePoint(stock_code=code, price=quote["price"]))

    db.commit()
    if filled_count:
        logger.info("run_matching_cycle: %d 筆訂單成交", filled_count)
    return filled_count


def prune_old_price_points(db: Session) -> int:
    """刪掉「今天以前」的分時快照。當日 OHLC 已經寫進 daily_bars，分時明細只有
    當天的頁面會用到，留著舊資料只會讓表一直長大。建議在每天開盤前的每日同步時呼叫。"""
    today_start = datetime.combine(datetime.now(TAIPEI_TZ).date(), time.min, tzinfo=TAIPEI_TZ)
    deleted = db.query(PricePoint).filter(PricePoint.ts < today_start).delete(synchronize_session=False)
    if deleted:
        db.commit()
        logger.info("prune_old_price_points: 清除 %d 筆過期分時資料", deleted)
    return deleted
