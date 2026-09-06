"""出場規則：回測模擬跟正式上線的每日選股都呼叫這裡，確保兩邊判斷完全一致。

四層依序判斷（先硬性、後條件式）：
1. 最長持有天數到了 → 強制出場
2. 損益率碰到停損或停利 → 強制出場
3. 還沒過最少持有天數 → 一律不出場（連規則條件都不看）
4. 規則條件成立 → 出場（沿用 services/strategy_conditions.py 的條件引擎）

損益率一律用「淨」的算法：買進時付手續費、賣出時付手續費加證交稅。台股的
證交稅只在賣出課徵，買進不課——所以買進成本只加手續費。
"""

from dataclasses import dataclass
from datetime import date

from app.config import settings
from app.models import DailyBar, PredictionModel
from app.services.strategy_conditions import evaluate_all

EXIT_MAX_HOLD = "max_hold_days"
EXIT_STOP_LOSS = "stop_loss"
EXIT_TAKE_PROFIT = "take_profit"
EXIT_RULE_CONDITION = "rule_condition"


def net_return_percent(entry_price: float, exit_price: float) -> float:
    """扣掉真實交易成本後的損益率（%）。

    買進實付：價格 × (1 + 手續費率)
    賣出實收：價格 × (1 - 手續費率 - 證交稅率)
    因為不追蹤股數，這裡直接用單價比值算，結果跟用任意固定股數算是一樣的。
    """
    cost = entry_price * (1 + settings.commission_rate)
    proceeds = exit_price * (1 - settings.commission_rate - settings.tax_rate)
    if cost <= 0:
        return 0.0
    return (proceeds - cost) / cost * 100


def gross_return_percent(entry_price: float, current_price: float) -> float:
    """未扣成本的帳面漲跌幅，只用來跟停損/停利門檻比較——使用者設定「跌 5% 就停損」
    時想的是股價跌 5%，不是「扣完手續費後的淨損益率跌 5%」。"""
    if entry_price <= 0:
        return 0.0
    return (current_price - entry_price) / entry_price * 100


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str | None = None


def decide_exit(
    model: PredictionModel,
    entry_date: date,
    entry_price: float,
    today: date,
    today_price: float,
    bars_until_today: list[DailyBar],
) -> ExitDecision:
    """判斷某一筆持有在 today 這天要不要出場。

    bars_until_today 是這檔股票「到今天為止」的日K（升冪、含今天），給規則條件
    算指標用——絕對不能包含今天之後的資料。
    """
    held_days = (today - entry_date).days

    if model.max_hold_days is not None and held_days >= model.max_hold_days:
        return ExitDecision(True, EXIT_MAX_HOLD)

    change = gross_return_percent(entry_price, today_price)
    if model.stop_loss_percent is not None and change <= -abs(model.stop_loss_percent):
        return ExitDecision(True, EXIT_STOP_LOSS)
    if model.take_profit_percent is not None and change >= abs(model.take_profit_percent):
        return ExitDecision(True, EXIT_TAKE_PROFIT)

    if model.min_hold_days is not None and held_days < model.min_hold_days:
        return ExitDecision(False)

    if model.sell_conditions and evaluate_all(model.sell_conditions, bars_until_today):
        return ExitDecision(True, EXIT_RULE_CONDITION)

    return ExitDecision(False)
