"""回測評估：拿訓練好的模型在「完全沒看過」的測試區間上重播一次，產出兩種東西：

1. `model_predictions`：測試集每一筆的「預測 vs 實際」，餵迴歸散佈圖跟分類校準曲線
2. `model_holdings(source=backtest)`：照真實選股/出場規則模擬出來的每一筆持有，
   餵交易績效散佈圖

模擬用的是 selection.run_daily_cycle——跟正式上線每天跑的是同一份程式碼，
所以「回測看到的行為」就是「上線後會發生的行為」。
"""

import logging
from collections import defaultdict
from datetime import date

import numpy as np
from sqlalchemy.orm import Session

from app.models import DailyBar, ModelHolding, ModelPrediction, PredictionModel
from app.services.ml.exit_rules import net_return_percent
from app.services.ml.selection import ModelBundle, OpenPosition, predict_rows, run_daily_cycle

logger = logging.getLogger(__name__)

EXIT_BACKTEST_END = "backtest_end"


def save_predictions(db: Session, model: PredictionModel, bundle: ModelBundle, test_rows: list[dict]) -> dict:
    """對測試集全部做一次預測並存檔，順便算出「這些預測準不準」的統計。"""
    if not test_rows:
        return {"prediction_count": 0}

    predicted_returns, probabilities = predict_rows(bundle, test_rows)
    for row, pred_return, probability in zip(test_rows, predicted_returns, probabilities):
        db.add(
            ModelPrediction(
                model_id=model.id,
                stock_code=row["stock_code"],
                as_of_date=row["as_of_date"],
                predicted_return_percent=float(pred_return),
                actual_return_percent=float(row["future_return_percent"]),
                predicted_probability=float(probability),
                actual_label=bool(row["label"]),
            )
        )
    db.commit()
    logger.info("save_predictions: 模型 %d 寫入 %d 筆測試集預測", model.id, len(test_rows))
    return {"prediction_count": len(test_rows)}


def simulate_trading(
    db: Session,
    model: PredictionModel,
    bundle: ModelBundle,
    test_rows: list[dict],
    bars_by_code: dict[str, list[DailyBar]],
) -> dict:
    """逐日重播測試區間的選股與出場，把每一筆模擬持有寫進 model_holdings。

    測試期結束時還開著的部位會用最後一天的收盤價強制平倉，理由標記成
    backtest_end——這樣每一筆都有完整報酬率可以畫圖，也清楚看得出來那不是
    真的訊號觸發的出場。
    """
    rows_by_date: dict[date, list[dict]] = defaultdict(list)
    for row in test_rows:
        rows_by_date[row["as_of_date"]].append(row)
    trading_days = sorted(rows_by_date.keys())
    if not trading_days:
        return {"holding_count": 0}

    # 逐日推進時要拿到「到當天為止」的日K給出場規則用，先建索引避免重複掃描
    bar_index: dict[str, dict[date, int]] = {
        code: {bar.trade_date: i for i, bar in enumerate(bars)} for code, bars in bars_by_code.items()
    }

    open_positions: list[OpenPosition] = []
    closed: list[dict] = []

    for today in trading_days:
        rows_today = rows_by_date[today]
        bars_until_today = {}
        for row in rows_today:
            code = row["stock_code"]
            index = bar_index.get(code, {}).get(today)
            if index is not None:
                bars_until_today[code] = bars_by_code[code][: index + 1]

        exits, entries = run_daily_cycle(
            model, bundle, today, rows_today, bars_until_today, open_positions
        )

        for action in exits:
            closed.append(
                {
                    "stock_code": action.position.stock_code,
                    "entry_date": action.position.entry_date,
                    "entry_price": action.position.entry_price,
                    "exit_date": today,
                    "exit_price": action.exit_price,
                    "reason": action.reason,
                }
            )
        exited_codes = {a.position.stock_code for a in exits}
        open_positions = [p for p in open_positions if p.stock_code not in exited_codes]

        for entry in entries:
            open_positions.append(
                OpenPosition(stock_code=entry.stock_code, entry_date=today, entry_price=entry.entry_price)
            )

    last_day = trading_days[-1]
    last_prices = {row["stock_code"]: row["close"] for row in rows_by_date[last_day]}
    for position in open_positions:
        exit_price = last_prices.get(position.stock_code, position.entry_price)
        closed.append(
            {
                "stock_code": position.stock_code,
                "entry_date": position.entry_date,
                "entry_price": position.entry_price,
                "exit_date": last_day,
                "exit_price": exit_price,
                "reason": EXIT_BACKTEST_END,
            }
        )

    returns = []
    for item in closed:
        ret = net_return_percent(item["entry_price"], item["exit_price"])
        returns.append(ret)
        db.add(
            ModelHolding(
                model_id=model.id,
                stock_code=item["stock_code"],
                source="backtest",
                entry_date=item["entry_date"],
                entry_price=item["entry_price"],
                exit_date=item["exit_date"],
                exit_price=item["exit_price"],
                status="closed",
                return_percent=ret,
                exit_reason=item["reason"],
            )
        )
    db.commit()

    wins = sum(1 for r in returns if r > 0)
    losses = sum(1 for r in returns if r < 0)
    stats = {
        "holding_count": len(returns),
        "average_return_percent": float(np.mean(returns)) if returns else None,
        "median_return_percent": float(np.median(returns)) if returns else None,
        "win_count": wins,
        "loss_count": losses,
        "win_rate": (wins / (wins + losses)) if (wins + losses) else None,
        "best_return_percent": float(max(returns)) if returns else None,
        "worst_return_percent": float(min(returns)) if returns else None,
    }
    logger.info("simulate_trading: 模型 %d 模擬 %d 筆持有，平均報酬 %s%%", model.id, len(returns), stats["average_return_percent"])
    return stats


def run_backtest(
    db: Session,
    model: PredictionModel,
    bundle: ModelBundle,
    test_rows: list[dict],
    bars_by_code: dict[str, list[DailyBar]],
) -> dict:
    prediction_stats = save_predictions(db, model, bundle, test_rows)
    trading_stats = simulate_trading(db, model, bundle, test_rows, bars_by_code)
    return {**prediction_stats, **trading_stats}
