"""公開的模型瀏覽 API：不需要登入，任何訪客都能看每個模型的績效、持有部位、
訓練參數與回測圖表資料。

因為是公開端點，所有數字一律從本地資料庫算出來，不打任何外部報價 API——
不然任何人重新整理頁面都會消耗外部 API 額度。
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ModelHolding, ModelPrediction, ModelScoringRun, PredictionModel, Stock
from app.schemas import (
    BacktestTradePointOut,
    CalibrationBucketOut,
    FeatureImportanceOut,
    FoldMetricsOut,
    FeatureOptionOut,
    ModelCatalogOut,
    ModelDetailOut,
    ModelHoldingOut,
    ModelPredictionPointOut,
    ModelSummaryOut,
    ModelTypeOptionOut,
    NetworkInfoOut,
    ScoreFormulaInfoOut,
    ScoringRunOut,
    WalkForwardSummaryOut,
)
from app.services.ml.dataset import LABEL_MODE_LABELS, SCALING_MODE_LABELS
from app.services.ml.exit_rules import net_return_percent
from app.services.ml.features import FEATURE_KEYS, FEATURE_LABELS
from app.services.ml.selection import TOP_N
from app.services.ml.train import (
    MODEL_TYPE_LABELS,
    MODEL_TYPES,
    NEURAL_MODEL_TYPES,
    SCORE_FORMULA_INFO,
    SEQUENCE_MODEL_TYPES,
)
from app.services.ml.performance import (
    latest_close_prices,
    summarize_holdings,
    training_metrics_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["public-models"])


@router.get("/catalog", response_model=ModelCatalogOut)
def get_catalog():
    """模型教學頁要用的「這個系統實際怎麼運作」清單。

    模型類型、選股分數公式、每天持有幾檔、手續費率全部從後端實作直接取，
    前端不自己抄一份——不然之後加了新模型類型或改了費率，教學頁會悄悄變成
    在講一個已經不存在的系統。
    """
    return ModelCatalogOut(
        model_types=[
            ModelTypeOptionOut(
                key=key,
                label=MODEL_TYPE_LABELS[key],
                is_neural=key in NEURAL_MODEL_TYPES,
                is_sequence=key in SEQUENCE_MODEL_TYPES,
            )
            for key in MODEL_TYPES
        ],
        score_formula=ScoreFormulaInfoOut(**SCORE_FORMULA_INFO),
        features=[FeatureOptionOut(key=key, label=FEATURE_LABELS[key]) for key in FEATURE_KEYS],
        top_n=TOP_N,
        commission_rate=settings.commission_rate,
        tax_rate=settings.tax_rate,
    )

# 散佈圖上限：測試集動輒兩萬筆，全部丟給瀏覽器畫既慢又看不出東西，
# 均勻抽樣後形狀一樣看得出來
MAX_SCATTER_POINTS = 3000
CALIBRATION_BUCKETS = 10


def _summary(model: PredictionModel, stats: dict) -> ModelSummaryOut:
    return ModelSummaryOut(
        id=model.id,
        model_family=model.model_family,
        version=model.version,
        model_type=model.model_type,
        status=model.status,
        is_archived=model.is_archived,
        n_days=model.n_days,
        threshold_percent=model.threshold_percent,
        label_mode=model.label_mode,
        label_mode_label=LABEL_MODE_LABELS.get(model.label_mode, model.label_mode),
        validation_mode=model.validation_mode,
        feature_scaling=model.feature_scaling,
        feature_scaling_label=SCALING_MODE_LABELS.get(model.feature_scaling, model.feature_scaling),
        industry_neutral=model.industry_neutral,
        score_formula=model.score_formula,
        training_duration_seconds=model.training_duration_seconds,
        training_progress=model.training_progress,
        error_message=model.error_message,
        created_at=model.created_at,
        trained_at=model.trained_at,
        open_holding_count=stats.get("open_holding_count", 0),
        closed_holding_count=stats.get("closed_holding_count", 0),
        average_realized_return_percent=stats.get("average_realized_return_percent"),
        average_unrealized_return_percent=stats.get("average_unrealized_return_percent"),
        total_unrealized_return_percent=stats.get("total_unrealized_return_percent"),
        **training_metrics_summary(model),
    )


@router.get("", response_model=list[ModelSummaryOut])
def list_public_models(db: Session = Depends(get_db)):
    """只列出訓練完成的模型（含已封存）。訓練中/失敗的是 admin 的中間狀態，
    對外顯示只會造成困惑。"""
    models = (
        db.query(PredictionModel)
        .filter(PredictionModel.status == "completed")
        .order_by(PredictionModel.model_family.asc(), PredictionModel.version.desc())
        .all()
    )
    stats = summarize_holdings(db, [m.id for m in models])
    return [_summary(m, stats.get(m.id, {})) for m in models]


def _sample(rows: list, limit: int) -> list:
    if len(rows) <= limit:
        return rows
    step = len(rows) / limit
    return [rows[int(i * step)] for i in range(limit)]


def _calibration(predictions: list[ModelPrediction]) -> list[CalibrationBucketOut]:
    """把預測機率分成 10 個桶，比較「模型說幾成」跟「實際幾成」。

    校準良好的模型，說 70% 的那批就該有大約七成真的達標；差很多就代表機率
    數字本身不能當信心水準用。
    """
    buckets: list[CalibrationBucketOut] = []
    for i in range(CALIBRATION_BUCKETS):
        low = i / CALIBRATION_BUCKETS
        high = (i + 1) / CALIBRATION_BUCKETS
        # 最後一桶要含右界，不然機率剛好 1.0 的樣本會被漏掉
        in_bucket = [
            p
            for p in predictions
            if low <= p.predicted_probability < high or (i == CALIBRATION_BUCKETS - 1 and p.predicted_probability == 1.0)
        ]
        if not in_bucket:
            continue
        buckets.append(
            CalibrationBucketOut(
                bucket_start=low,
                bucket_end=high,
                average_predicted=sum(p.predicted_probability for p in in_bucket) / len(in_bucket),
                actual_rate=sum(1 for p in in_bucket if p.actual_label) / len(in_bucket),
                sample_count=len(in_bucket),
            )
        )
    return buckets


def _holding_out(holding: ModelHolding, names: dict[str, str], prices: dict[str, float], today) -> ModelHoldingOut:
    current_price = prices.get(holding.stock_code) if holding.status == "open" else None
    return_percent = holding.return_percent
    if holding.status == "open" and current_price is not None:
        return_percent = net_return_percent(holding.entry_price, current_price)
    end = holding.exit_date or today
    return ModelHoldingOut(
        stock_code=holding.stock_code,
        stock_name=names.get(holding.stock_code, holding.stock_code),
        entry_date=holding.entry_date,
        entry_price=holding.entry_price,
        exit_date=holding.exit_date,
        exit_price=holding.exit_price,
        status=holding.status,
        return_percent=return_percent,
        exit_reason=holding.exit_reason,
        held_days=(end - holding.entry_date).days,
        current_price=current_price,
    )


@router.get("/{model_id}", response_model=ModelDetailOut)
def get_public_model(model_id: int, db: Session = Depends(get_db)):
    from datetime import date as date_cls

    model = db.get(PredictionModel, model_id)
    if model is None or model.status != "completed":
        raise HTTPException(status_code=404, detail="模型不存在")

    stats = summarize_holdings(db, [model.id])
    metrics = model.metrics or {}

    predictions = db.query(ModelPrediction).filter(ModelPrediction.model_id == model.id).all()
    regression_points = [
        ModelPredictionPointOut(
            predicted_return_percent=p.predicted_return_percent,
            actual_return_percent=p.actual_return_percent,
            predicted_probability=p.predicted_probability,
            actual_label=p.actual_label,
        )
        for p in _sample(predictions, MAX_SCATTER_POINTS)
    ]

    backtest_holdings = (
        db.query(ModelHolding)
        .filter(ModelHolding.model_id == model.id, ModelHolding.source == "backtest")
        .order_by(ModelHolding.entry_date.asc())
        .all()
    )
    backtest_trades = [
        BacktestTradePointOut(
            entry_date=h.entry_date,
            return_percent=h.return_percent or 0.0,
            stock_code=h.stock_code,
            exit_reason=h.exit_reason,
        )
        for h in backtest_holdings
    ]

    live_holdings = (
        db.query(ModelHolding)
        .filter(ModelHolding.model_id == model.id, ModelHolding.source == "live")
        .order_by(ModelHolding.entry_date.desc())
        .all()
    )
    codes = {h.stock_code for h in live_holdings}
    names = dict(db.query(Stock.code, Stock.name).filter(Stock.code.in_(codes)).all()) if codes else {}
    prices = latest_close_prices(db, {h.stock_code for h in live_holdings if h.status == "open"})
    today = date_cls.today()

    runs = (
        db.query(ModelScoringRun)
        .filter(ModelScoringRun.model_id == model.id)
        .order_by(ModelScoringRun.run_date.desc())
        .limit(30)
        .all()
    )
    durations = [r.duration_seconds for r in runs if r.status == "success"]

    def importance_out(items: list[dict]) -> list[FeatureImportanceOut]:
        return [
            FeatureImportanceOut(
                feature=item["feature"],
                label=FEATURE_LABELS.get(item["feature"], item["feature"]),
                importance=item["importance"],
            )
            for item in items or []
        ]

    return ModelDetailOut(
        summary=_summary(model, stats.get(model.id, {})),
        feature_config=list(model.feature_config),
        feature_labels=[FEATURE_LABELS.get(k, k) for k in model.feature_config],
        min_hold_days=model.min_hold_days,
        max_hold_days=model.max_hold_days,
        stop_loss_percent=model.stop_loss_percent,
        take_profit_percent=model.take_profit_percent,
        sell_conditions=list(model.sell_conditions),
        score_weights=model.score_weights,
        score_formula_info=ScoreFormulaInfoOut(**SCORE_FORMULA_INFO),
        train_start=model.train_start,
        train_end=model.train_end,
        validation_start=model.validation_start,
        validation_end=model.validation_end,
        test_start=model.test_start,
        test_end=model.test_end,
        metrics=metrics,
        folds=[FoldMetricsOut(**f) for f in metrics.get('folds', [])],
        walk_forward=(
            WalkForwardSummaryOut(**metrics['walk_forward']) if metrics.get('walk_forward') else None
        ),
        warnings=metrics.get("warnings", []),
        network=NetworkInfoOut(**metrics["network"]) if metrics.get("network") else None,
        regression_points=regression_points,
        calibration_buckets=_calibration(predictions),
        backtest_trades=backtest_trades,
        regression_feature_importance=importance_out(metrics.get("regression_feature_importance", [])),
        classification_feature_importance=importance_out(metrics.get("classification_feature_importance", [])),
        open_holdings=[_holding_out(h, names, prices, today) for h in live_holdings if h.status == "open"],
        closed_holdings=[_holding_out(h, names, prices, today) for h in live_holdings if h.status == "closed"],
        scoring_runs=[
            ScoringRunOut(run_date=r.run_date, duration_seconds=r.duration_seconds, status=r.status) for r in runs
        ],
        average_scoring_seconds=(sum(durations) / len(durations)) if durations else None,
    )
