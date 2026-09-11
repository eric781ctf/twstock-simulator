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
from app.services.ml.exit_rules import decide_exit, limit_state
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
    特徵順序。特徵順序一定要跟訓練當下一致，不然欄位會對錯。

    sequence_length 只有 GRU/LSTM 會設；有值就代表這個模型吃的是「連續 T 天的
    視窗」，餵進去的特徵列必須先經過 sequences.index_feature_rows 掛上歷史參照。
    """

    regressor: object
    classifier: object
    feature_keys: list[str]
    scaler_mean: np.ndarray
    scaler_std: np.ndarray
    sequence_length: int | None = None
    # 訓練時用的特徵標準化方式。推論時必須用同一種，不然分布完全對不上
    feature_scaling: str = "zscore"
    # 訓練時有沒有做產業中性化。推論時必須一致，不然分布對不上
    industry_neutral: bool = False


# 一次推論的最大筆數。回測時 save_predictions 會一口氣丟進近十萬列，序列模型
# 每列還要展開成 T×F，不分批的話光是組輸入就會吃掉好幾百 MB。
PREDICT_BATCH = 8192


def _build_input(bundle: ModelBundle, rows: list[dict]) -> np.ndarray:
    """組出模型要的輸入：表格式模型是 (N, F)，序列模型是 (N, T, F)。"""
    if bundle.sequence_length:
        from app.services.ml.sequences import stack_sequences

        x = stack_sequences(rows, bundle.sequence_length)
    else:
        x = np.zeros((len(rows), len(bundle.feature_keys)), dtype=np.float64)
        for i, row in enumerate(rows):
            for j, key in enumerate(bundle.feature_keys):
                value = row.get(key)
                x[i, j] = float(value) if value is not None and np.isfinite(float(value)) else np.nan
    return apply_scaler(x, bundle.scaler_mean, bundle.scaler_std)


def predict_rows(bundle: ModelBundle, rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """對特徵列做預測，回傳 (預期報酬率%, 達標機率)。"""
    if not rows:
        return np.array([]), np.array([])

    returns_chunks: list[np.ndarray] = []
    probability_chunks: list[np.ndarray] = []

    for start in range(0, len(rows), PREDICT_BATCH):
        chunk = rows[start : start + PREDICT_BATCH]
        x = _build_input(bundle, chunk)
        returns_chunks.append(np.asarray(bundle.regressor.predict(x), dtype=float))
        if hasattr(bundle.classifier, "predict_proba"):
            probability_chunks.append(np.asarray(bundle.classifier.predict_proba(x)[:, 1], dtype=float))
        else:
            probability_chunks.append(np.asarray(bundle.classifier.predict(x), dtype=float))

    return np.concatenate(returns_chunks), np.concatenate(probability_chunks)


def run_daily_cycle(
    model: PredictionModel,
    bundle: ModelBundle,
    today: date,
    rows_today: list[dict],
    signal_rows: list[dict],
    bars_until_today: dict[str, list[DailyBar]],
    open_positions: list[OpenPosition],
) -> tuple[list[ExitAction], list[EntryAction]]:
    """跑某一天的出場判斷與進場選股。

    rows_today 是這一天所有可評估股票的特徵列，提供成交價與漲跌停判斷；
    bars_until_today 是各股票「到今天為止」的日K（給出場規則算指標用）。

    **signal_rows 是前一個交易日的特徵列，進場排名一律用它算。** 特徵是用
    收盤價算出來的，所以訊號成形的當下今天的盤已經收了——拿今天的訊號配
    今天的收盤價，等於用一個當下取不到的價格成交。實測這個假設本身就佔了
    八成以上的回測績效，是整條管線裡最大的一個 look-ahead。
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
        if decision.should_exit and limit_state(bars_until_today.get(position.stock_code, [])) == "down":
            # 跌停當天沒有買方，賣不掉，只能續抱到隔天再判斷一次
            still_held.add(position.stock_code)
        elif decision.should_exit:
            exits.append(ExitAction(position=position, exit_price=price, reason=decision.reason or "rule_condition"))
        else:
            still_held.add(position.stock_code)

    open_slots = TOP_N - len(still_held)
    if open_slots <= 0 or not signal_rows:
        return exits, []

    # 今天買得到的價格。訊號來自昨天，但成交價與漲跌停都要看今天
    tradable = {
        row["stock_code"]: float(row["close"])
        for row in rows_today
        if limit_state(bars_until_today.get(row["stock_code"], [])) != "up"
    }
    candidates = [
        row
        for row in signal_rows
        if row["stock_code"] not in still_held and row["stock_code"] in tradable
    ]
    if bundle.sequence_length:
        # 序列模型對「前面歷史不足 T 天」的股票根本算不出分數（剛上市、或本地
        # 日K還沒回補到那麼早）。這些直接不列入候選，不用補零硬湊一段假歷史。
        from app.services.ml.sequences import filter_rows_with_history

        candidates = filter_rows_with_history(candidates, bundle.sequence_length)
    if not candidates:
        return exits, []

    predicted_returns, probabilities = predict_rows(bundle, candidates)
    scores = compute_scores(predicted_returns, probabilities, model.score_weights)

    order = np.argsort(scores)[::-1][:open_slots]
    # 分數門檻：寧可少買也不要為了湊滿 10 檔而買進分數平庸的標的。
    # 分數是當天全市場的 z-score 加權平均，所以 0 代表「當天的平均水準」，
    # 門檻是相對的——設 1.0 是「至少高於當天市場一個標準差」，不是保證會漲
    if model.min_score is not None:
        order = [i for i in order if scores[i] >= model.min_score]

    entries = [
        EntryAction(
            stock_code=candidates[i]["stock_code"],
            # 訊號是昨天的，成交價是今天的
            entry_price=tradable[candidates[i]["stock_code"]],
            score=float(scores[i]),
            predicted_return_percent=float(predicted_returns[i]),
            predicted_probability=float(probabilities[i]),
        )
        for i in order
    ]
    return exits, entries
