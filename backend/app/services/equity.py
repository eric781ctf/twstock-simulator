"""每日績效快照：幫每個帳戶算出「今天」的現金、部位市值、總資產，寫進
equity_snapshots，給績效走勢圖用。市值故意用 daily_bars 的最新收盤價計算，
不打即時報價 API——這個排程每天只需要跑一次，用本地已經同步好的資料就夠，
沒必要為了一張走勢圖多消耗 mis.twse 的請求額度。"""

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.models import Account, DailyBar, EquitySnapshot, Position

logger = logging.getLogger(__name__)


def _latest_close_by_code(db: Session, codes: set[str]) -> dict[str, float]:
    if not codes:
        return {}
    rows = (
        db.query(DailyBar.stock_code, DailyBar.trade_date, DailyBar.close)
        .filter(DailyBar.stock_code.in_(codes))
        .order_by(DailyBar.stock_code.asc(), DailyBar.trade_date.desc())
        .all()
    )
    latest: dict[str, float] = {}
    for code, _trade_date, close in rows:
        if code not in latest:  # 每檔股票第一次出現（依日期降冪排序）就是最新一筆
            latest[code] = close
    return latest


def snapshot_all_accounts_equity(db: Session) -> int:
    today = date.today()
    accounts = db.query(Account).all()
    if not accounts:
        return 0

    positions = db.query(Position).filter(Position.quantity > 0).all()
    positions_by_account: dict[int, list[Position]] = {}
    for p in positions:
        positions_by_account.setdefault(p.account_id, []).append(p)

    latest_close = _latest_close_by_code(db, {p.stock_code for p in positions})

    existing = {
        s.account_id: s
        for s in db.query(EquitySnapshot).filter(EquitySnapshot.snapshot_date == today).all()
    }

    count = 0
    for account in accounts:
        market_value = 0.0
        for p in positions_by_account.get(account.id, []):
            # 找不到本地收盤價（例如剛上市、資料還沒同步到）就用成本價估，
            # 不要讓這筆部位直接從市值消失。
            price = latest_close.get(p.stock_code, float(p.avg_cost))
            market_value += price * p.quantity

        cash = float(account.cash_balance)
        total_assets = cash + market_value

        snapshot = existing.get(account.id)
        if snapshot is None:
            snapshot = EquitySnapshot(account_id=account.id, snapshot_date=today)
            db.add(snapshot)
        snapshot.cash_balance = cash
        snapshot.market_value = market_value
        snapshot.total_assets = total_assets
        count += 1

    db.commit()
    logger.info("snapshot_all_accounts_equity: 完成 %d 個帳戶的每日績效快照", count)
    return count
