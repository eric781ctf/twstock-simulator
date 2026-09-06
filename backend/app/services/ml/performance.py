"""模型績效彙總：已實現與未實現的平均損益率。

兩個數字都給、不合併成一個「代表分數」——已實現是真的落袋的結果，未實現是
還在波動中的帳面數字，兩者性質不同，怎麼解讀留給看的人自己判斷。

未實現損益用本地 daily_bars 的最新收盤價計算，不打即時報價 API：這個頁面是
公開的，任何訪客都能打，掛上即時報價會直接把外部 API 額度燒光。
"""

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DailyBar, ModelHolding
from app.services.ml.exit_rules import net_return_percent


def latest_close_prices(db: Session, codes: set[str]) -> dict[str, float]:
    """每檔股票最新一筆日K的收盤價。"""
    if not codes:
        return {}
    latest_dates = (
        db.query(DailyBar.stock_code, func.max(DailyBar.trade_date).label("max_date"))
        .filter(DailyBar.stock_code.in_(codes))
        .group_by(DailyBar.stock_code)
        .subquery()
    )
    rows = (
        db.query(DailyBar.stock_code, DailyBar.close)
        .join(
            latest_dates,
            (DailyBar.stock_code == latest_dates.c.stock_code) & (DailyBar.trade_date == latest_dates.c.max_date),
        )
        .all()
    )
    return {code: close for code, close in rows}


def summarize_holdings(db: Session, model_ids: list[int]) -> dict[int, dict]:
    """一次算出多個模型的持有統計，避免列表頁對每個模型各查一次資料庫。
    只看 source=live 的持有——回測模擬出來的不是這個模型「真的」的績效。"""
    if not model_ids:
        return {}

    holdings = (
        db.query(ModelHolding)
        .filter(ModelHolding.model_id.in_(model_ids), ModelHolding.source == "live")
        .all()
    )
    by_model: dict[int, list[ModelHolding]] = defaultdict(list)
    for h in holdings:
        by_model[h.model_id].append(h)

    open_codes = {h.stock_code for h in holdings if h.status == "open"}
    prices = latest_close_prices(db, open_codes)

    result: dict[int, dict] = {}
    for model_id in model_ids:
        items = by_model.get(model_id, [])
        realized = [h.return_percent for h in items if h.status == "closed" and h.return_percent is not None]

        unrealized: list[float] = []
        for h in items:
            if h.status != "open":
                continue
            price = prices.get(h.stock_code)
            if price is not None:
                unrealized.append(net_return_percent(h.entry_price, price))

        result[model_id] = {
            "open_holding_count": sum(1 for h in items if h.status == "open"),
            "closed_holding_count": len(realized),
            "average_realized_return_percent": (sum(realized) / len(realized)) if realized else None,
            "average_unrealized_return_percent": (sum(unrealized) / len(unrealized)) if unrealized else None,
        }
    return result
