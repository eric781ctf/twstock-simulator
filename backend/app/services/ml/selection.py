"""每日選股循環：先判斷手上的要不要賣，再從當天全市場挑出分數前 N 名買進。

回測（逐日重播歷史）跟正式上線（每天收盤後跑一次）都呼叫 run_daily_cycle，
差別只在呼叫端把結果寫進記憶體還是資料庫。共用同一份邏輯是刻意的——不然
「回測時的行為」跟「上線後的行為」很容易在改動中悄悄分岔。
"""

import logging
from dataclasses import dataclass
from datetime import date

import numpy as np

from app.models import DailyBar, PredictionModel
from app.services.ml.dataset import apply_scaler, to_matrix
from app.services.ml.exit_rules import decide_exit
from app.services.ml.train import compute_scores

logger = logging.getLogger(__name__)

TOP_N = 10  # 每天最多持有幾檔


@dataclass
class OpenPosition:
    stock_code: str
    entry_date: date
    entry_price: float
    ref: object = None  # 呼叫端自己要用的參照（例如資料庫裡的 ModelHolding）


@dataclass
class ExitAction:
    position: OpenPosition
    exit_price: float
    reason: str


@dataclass
class EntryAction:
    stock_code: str
    entry_price: float
    score: float
    predicted_return_percent: float
    predicted_probability: float


@dataclass
class ModelBundle:
    """訓練完成後推論需要的一整組東西：兩個模型 + 訓練集算出來的標準化參數 +
    特徵順序。特徵順序一定要跟訓練當下一致，不然欄位會對錯。"""

    regressor: object
    classifier: object
    feature_keys: list[str]
    scaler_mean: np.ndarray
    scaler_std: np.ndarray


def predict_rows(bundle: ModelBundle, rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """對特徵列做預測，回傳 (預期報酬率%, 達標機率)。"""
    if not rows:
        return np.array([]), np.array([])

    x = np.zeros((len(rows), len(bundle.feature_keys)), dtype=np.float64)
    for i, row in enumerate(rows):
        for j, key in enumerate(bundle.feature_keys):
            value = row.get(key)
            x[i, j] = float(value) if value is not None and np.isfinite(float(value)) else np.nan
    x = apply_scaler(x, bundle.scaler_mean, bundle.scaler_std)

    predicted_returns = np.asarray(bundle.regressor.predict(x), dtype=float)
    if hasattr(bundle.classifier, "predict_proba"):
        probabilities = np.asarray(bundle.classifier.predict_proba(x)[:, 1], dtype=float)
    else:
        probabilities = np.asarray(bundle.classifier.predict(x), dtype=float)
    return predicted_returns, probabilities


def run_daily_cycle(
    model: PredictionModel,
    bundle: ModelBundle,
    today: date,
    rows_today: list[dict],
    bars_until_today: dict[str, list[DailyBar]],
    open_positions: list[OpenPosition],
) -> tuple[list[ExitAction], list[EntryAction]]:
    """跑某一天的出場判斷與進場選股。

    rows_today 是這一天所有可評估股票的特徵列；bars_until_today 是各股票「到
    今天為止」的日K（給出場規則算指標用，不含未來）。
    """
    price_today = {row["stock_code"]: row["close"] for row in rows_today}

    exits: list[ExitAction] = []
    still_held: set[str] = set()
    for position in open_positions:
        price = price_today.get(position.stock_code)
        if price is None:
            # 這檔今天沒有新的K棒（停牌之類），無從判斷也無從成交，先續抱
            still_held.add(position.stock_code)
            continue
        decision = decide_exit(
            model,
            entry_date=position.entry_date,
            entry_price=position.entry_price,
            today=today,
            today_price=price,
            bars_until_today=bars_until_today.get(position.stock_code, []),
        )
        if decision.should_exit:
            exits.append(ExitAction(position=position, exit_price=price, reason=decision.reason or "rule_condition"))
        else:
            still_held.add(position.stock_code)

    open_slots = TOP_N - len(still_held)
    if open_slots <= 0 or not rows_today:
        return exits, []

    candidates = [row for row in rows_today if row["stock_code"] not in still_held]
    if not candidates:
        return exits, []

    predicted_returns, probabilities = predict_rows(bundle, candidates)
    scores = compute_scores(predicted_returns, probabilities, model.score_formula, model.score_weights)

    order = np.argsort(scores)[::-1][:open_slots]
    entries = [
        EntryAction(
            stock_code=candidates[i]["stock_code"],
            entry_price=float(candidates[i]["close"]),
            score=float(scores[i]),
            predicted_return_percent=float(predicted_returns[i]),
            predicted_probability=float(probabilities[i]),
        )
        for i in order
    ]
    return exits, entries
