"""策略回測：拿策略設定的買賣條件，套用在本地已經累積的歷史日K資料上逐日
重播，模擬出一條績效走勢曲線，不會真的下單也不影響任何帳戶資料。刻意跟
services/strategy_engine.py（正式上線後每分鐘掃描一次的即時引擎）共用同一套
判斷邏輯（evaluate_all/compute_rank_value），確保「回測看到的訊號」跟「策略
啟用後實際會不會下單」是同一個答案，不會有回測跟實盤兜不起來的落差。

跟即時引擎的差異：
- 即時引擎每分鐘重跑、靠 StrategyTrade 表去重「今天已經下過單」；回測本來
  就是逐日跑一次，天然不會重複下單，不需要額外的去重表。
- 即時引擎的成交價是「當下市價」（要打報價 API）；回測只有日K資料，統一用
  當天收盤價成交，等於假設訊號出現當天就能用收盤價進出——這是歷史回測常見
  的簡化假設，不是撮合機制的 bug。
"""

import bisect
import logging
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import DailyBar, Strategy
from app.services.fees import compute_amount, compute_commission, compute_tax
from app.services.indicators import compute_rank_value
from app.services.strategy_conditions import evaluate_all

logger = logging.getLogger(__name__)

LOOKBACK_CALENDAR_DAYS = 130  # 跟 strategy_engine.LOOKBACK_DAYS 對齊，湊出約 60 個交易日給 MA60/KD 用
MIN_BARS_REQUIRED = 15
MAX_BACKTEST_CALENDAR_DAYS = 370  # 留一點餘裕給前端的「近一年」選項（365 天）
STALE_BAR_TOLERANCE_DAYS = 10  # 超過這麼多天沒有新K棒的股票，回測期間視為停牌/下市，跳過


class BacktestError(Exception):
    pass


def run_backtest(db: Session, strategy: Strategy, start_date: date, end_date: date, initial_cash: float) -> dict:
    if start_date >= end_date:
        raise BacktestError("結束日期必須晚於起始日期")
    if (end_date - start_date).days > MAX_BACKTEST_CALENDAR_DAYS:
        raise BacktestError(f"回測區間最長 {MAX_BACKTEST_CALENDAR_DAYS} 天，請縮短範圍")

    fetch_from = start_date - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    rows = (
        db.query(DailyBar)
        .filter(DailyBar.trade_date >= fetch_from, DailyBar.trade_date <= end_date)
        .order_by(DailyBar.stock_code.asc(), DailyBar.trade_date.asc())
        .all()
    )

    bars_by_code: dict[str, list[DailyBar]] = {}
    for row in rows:
        bars_by_code.setdefault(row.stock_code, []).append(row)
    dates_by_code: dict[str, list[date]] = {code: [b.trade_date for b in bars] for code, bars in bars_by_code.items()}

    trading_days = sorted({row.trade_date for row in rows if start_date <= row.trade_date <= end_date})
    if not trading_days:
        raise BacktestError("這段期間沒有足夠的本地日K資料可以回測，請選擇較近期的區間")

    warning = None
    if not strategy.buy_conditions:
        warning = "此策略沒有設定買進條件，回測期間不會建立任何新部位"

    cash = initial_cash
    positions: dict[str, dict] = {}  # stock_code -> {"quantity": int, "avg_cost": float, "last_price": float}
    equity_curve: list[dict] = []
    trade_count = 0
    win_count = 0
    loss_count = 0
    peak = initial_cash
    max_drawdown_percent = 0.0

    for day in trading_days:
        day_bars_by_code: dict[str, list[DailyBar]] = {}
        for code, dates in dates_by_code.items():
            idx = bisect.bisect_right(dates, day)
            if idx == 0:
                continue
            if (day - dates[idx - 1]).days > STALE_BAR_TOLERANCE_DAYS:
                continue
            day_bars_by_code[code] = bars_by_code[code][:idx]

        # 賣出：只檢查目前持有、且今天有新K棒的股票
        for code in list(positions.keys()):
            bars = day_bars_by_code.get(code)
            if not bars or bars[-1].trade_date != day or len(bars) < MIN_BARS_REQUIRED:
                continue
            if not evaluate_all(strategy.sell_conditions, bars):
                continue
            pos = positions[code]
            price = bars[-1].close
            amount = compute_amount(price, pos["quantity"])
            fee = compute_commission(amount)
            tax = compute_tax(amount)
            net_proceeds = amount - fee - tax
            pnl = net_proceeds - pos["avg_cost"] * pos["quantity"]
            cash += net_proceeds
            trade_count += 1
            if pnl > 0:
                win_count += 1
            elif pnl < 0:
                loss_count += 1
            del positions[code]

        # 買進：全市場掃描本地資料足夠、今天有新K棒、還沒持有的股票
        if strategy.buy_conditions:
            candidates: list[tuple[str, float, float]] = []
            for code, bars in day_bars_by_code.items():
                if code in positions or bars[-1].trade_date != day or len(bars) < MIN_BARS_REQUIRED:
                    continue
                if not evaluate_all(strategy.buy_conditions, bars):
                    continue
                rank_value = compute_rank_value(strategy.rank_by, bars)
                if rank_value is None:
                    continue
                candidates.append((code, rank_value, bars[-1].close))

            candidates.sort(key=lambda item: item[1], reverse=(strategy.rank_direction == "desc"))
            for code, _rank_value, price in candidates[: strategy.top_n]:
                amount = compute_amount(price, strategy.quantity)
                fee = compute_commission(amount)
                total_cost = amount + fee
                if cash < total_cost:
                    continue
                cash -= total_cost
                positions[code] = {
                    "quantity": strategy.quantity,
                    "avg_cost": total_cost / strategy.quantity,
                    "last_price": price,
                }
                trade_count += 1

        market_value = 0.0
        for code, pos in positions.items():
            bars = day_bars_by_code.get(code)
            if bars:
                pos["last_price"] = bars[-1].close
            market_value += pos["last_price"] * pos["quantity"]

        total_assets = cash + market_value
        peak = max(peak, total_assets)
        if peak > 0:
            max_drawdown_percent = max(max_drawdown_percent, (peak - total_assets) / peak * 100)
        equity_curve.append({"date": day.isoformat(), "total_assets": total_assets})

    final_assets = equity_curve[-1]["total_assets"] if equity_curve else initial_cash
    total_return_percent = (final_assets - initial_cash) / initial_cash * 100 if initial_cash else 0.0
    decided = win_count + loss_count

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "initial_cash": initial_cash,
        "final_assets": final_assets,
        "total_return_percent": total_return_percent,
        "max_drawdown_percent": max_drawdown_percent,
        "trade_count": trade_count,
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": (win_count / decided) if decided else None,
        "equity_curve": equity_curve,
        "warning": warning,
    }
