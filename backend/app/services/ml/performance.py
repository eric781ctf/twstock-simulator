"""模型績效彙總：已實現與未實現的損益率。

兩個數字都給、不合併成一個「代表分數」——已實現是真的落袋的結果，未實現是
還在波動中的帳面數字，兩者性質不同，怎麼解讀留給看的人自己判斷。

未實現損益用本地 daily_bars 的最新收盤價計算，不打即時報價 API：這個頁面是
公開的，任何訪客都能打，掛上即時報價會直接把外部 API 額度燒光。
"""

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DailyBar, ModelHolding, PredictionModel
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


def portfolio_return_percent(pairs: list[tuple[float, float]]) -> float | None:
    """一籃子部位的整體損益率：總市值比總成本。

    跟「每檔損益率取平均」是不同的數字。平均是等權（每檔投一樣多錢），這裡是
    **每檔各一股**，所以高價股的權重比較大——台積電漲 1% 對這個數字的影響會
    大過某檔 20 元的小型股漲 1%。兩種都合理，取決於你想問哪個問題。

    成本與市值都含交易成本，跟系統其他地方的損益率算法一致：買進實付價格
    加手續費，賣出實收價格扣手續費與證交稅。
    """
    cost = sum(entry * (1 + settings.commission_rate) for entry, _ in pairs)
    if cost <= 0:
        return None
    proceeds = sum(
        current * (1 - settings.commission_rate - settings.tax_rate) for _, current in pairs
    )
    return (proceeds - cost) / cost * 100


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
        open_pairs: list[tuple[float, float]] = []
        for h in items:
            if h.status != "open":
                continue
            price = prices.get(h.stock_code)
            if price is not None:
                unrealized.append(net_return_percent(h.entry_price, price))
                open_pairs.append((h.entry_price, price))

        result[model_id] = {
            "open_holding_count": sum(1 for h in items if h.status == "open"),
            "closed_holding_count": len(realized),
            "average_realized_return_percent": (sum(realized) / len(realized)) if realized else None,
            "average_unrealized_return_percent": (sum(unrealized) / len(unrealized)) if unrealized else None,
            "total_unrealized_return_percent": portfolio_return_percent(open_pairs),
        }
    return result


def training_metrics_summary(model: PredictionModel) -> dict:
    """從 metrics JSON 挑出列表頁要顯示的幾個數字。

    滾動驗證時取各折的平均與標準差；單次切分時 walk_forward 不存在，退回那
    一次的測試分數，此時沒有標準差也沒有「幾折為正」可談，所以留 None——
    寫成 0 會讓人以為量過而且是 0。
    """
    metrics = model.metrics or {}
    walk_forward = metrics.get("walk_forward") or {}
    rank_ic = walk_forward.get("test_rank_ic") or {}
    auc = walk_forward.get("test_auc") or {}
    backtest = metrics.get("backtest") or {}
    test = metrics.get("test") or {}

    if rank_ic:
        ic_mean, ic_std = rank_ic.get("mean"), rank_ic.get("std")
        auc_mean = auc.get("mean")
        folds, positive = rank_ic.get("count"), rank_ic.get("positive_folds")
    else:
        ic_mean, ic_std = test.get("rank_ic"), None
        auc_mean = test.get("auc")
        folds, positive = None, None

    return {
        "test_rank_ic": ic_mean,
        "test_rank_ic_std": ic_std,
        "test_auc": auc_mean,
        "fold_count": folds,
        "positive_folds": positive,
        "backtest_average_return_percent": backtest.get("average_return_percent"),
        "backtest_win_rate": backtest.get("win_rate"),
        "backtest_holding_count": backtest.get("holding_count"),
    }
