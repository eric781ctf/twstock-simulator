"""模型管理 API（admin 專用）。公開的瀏覽端點在 PR4 另外加。

訓練是丟到背景 process pool 跑的，這裡的 POST 只負責建立一筆 queued 的模型
版本就馬上回應——不能讓 HTTP 請求等在那裡，訓練動輒數十秒到數分鐘。
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PredictionModel, User
from app.schemas import (
    FeatureOptionOut,
    ModelSummaryOut,
    ModelTrainRequest,
    ModelTypeOptionOut,
    ScoreFormulaInfoOut,
    TrainDefaultsOut,
)
from app.services.auth import require_admin
from app.services.ml.features import DEFAULT_FEATURES, FEATURE_KEYS, FEATURE_LABELS
from app.services.ml.inference import latest_bar_date
from app.services.ml.performance import summarize_holdings
from app.services.ml.train import (
    MODEL_TYPE_LABELS,
    MODEL_TYPES,
    NEURAL_MODEL_TYPES,
    SCORE_FORMULA_INFO,
    SCORE_FORMULA_KEY,
)
from app.services.ml.training_runner import run_training_job, suggest_split_dates
from app.services.strategy_conditions import ConditionValidationError, validate_conditions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/models", tags=["models"])


@router.get("/train-defaults", response_model=TrainDefaultsOut)
def get_train_defaults(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    latest = latest_bar_date(db)
    return TrainDefaultsOut(
        latest_data_date=latest,
        **suggest_split_dates(latest),
        default_features=DEFAULT_FEATURES,
        features=[FeatureOptionOut(key=key, label=FEATURE_LABELS[key]) for key in FEATURE_KEYS],
        model_types=[
            ModelTypeOptionOut(key=key, label=MODEL_TYPE_LABELS[key], is_neural=key in NEURAL_MODEL_TYPES)
            for key in MODEL_TYPES
        ],
        score_formula=ScoreFormulaInfoOut(**SCORE_FORMULA_INFO),
    )


def _to_summary(model: PredictionModel, stats: dict) -> ModelSummaryOut:
    return ModelSummaryOut(
        id=model.id,
        model_family=model.model_family,
        version=model.version,
        model_type=model.model_type,
        status=model.status,
        is_archived=model.is_archived,
        n_days=model.n_days,
        threshold_percent=model.threshold_percent,
        score_formula=model.score_formula,
        training_duration_seconds=model.training_duration_seconds,
        error_message=model.error_message,
        created_at=model.created_at,
        trained_at=model.trained_at,
        open_holding_count=stats.get("open_holding_count", 0),
        closed_holding_count=stats.get("closed_holding_count", 0),
        average_realized_return_percent=stats.get("average_realized_return_percent"),
        average_unrealized_return_percent=stats.get("average_unrealized_return_percent"),
    )


@router.get("", response_model=list[ModelSummaryOut])
def list_models(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    models = db.query(PredictionModel).order_by(PredictionModel.id.desc()).all()
    stats = summarize_holdings(db, [m.id for m in models])
    return [_to_summary(m, stats.get(m.id, {})) for m in models]


@router.post("", response_model=ModelSummaryOut, status_code=201)
async def create_model(
    payload: ModelTrainRequest, db: Session = Depends(get_db), _: User = Depends(require_admin)
):
    unknown = [key for key in payload.feature_config if key not in FEATURE_KEYS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"不支援的特徵：{', '.join(unknown)}")

    try:
        validate_conditions(payload.sell_conditions)
    except ConditionValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 同一個 model_family 每次訓練都是新版本，版本號自動接續
    current_max = (
        db.query(func.max(PredictionModel.version))
        .filter(PredictionModel.model_family == payload.model_family)
        .scalar()
    )
    model = PredictionModel(
        model_family=payload.model_family,
        version=(current_max or 0) + 1,
        model_type=payload.model_type,
        feature_config=payload.feature_config,
        n_days=payload.n_days,
        threshold_percent=payload.threshold_percent,
        score_formula=SCORE_FORMULA_KEY,
        score_weights=payload.score_weights,
        network_config=payload.network_config.model_dump() if payload.network_config else None,
        min_hold_days=payload.min_hold_days,
        max_hold_days=payload.max_hold_days,
        stop_loss_percent=payload.stop_loss_percent,
        take_profit_percent=payload.take_profit_percent,
        sell_conditions=payload.sell_conditions,
        train_start=payload.train_start,
        train_end=payload.train_end,
        validation_start=payload.validation_start,
        validation_end=payload.validation_end,
        test_start=payload.test_start,
        test_end=payload.test_end,
        status="queued",
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    asyncio.create_task(run_training_job(model.id))
    logger.info("已排入訓練：模型 %d（%s v%d）", model.id, model.model_family, model.version)
    return _to_summary(model, {})


def _get_model(db: Session, model_id: int) -> PredictionModel:
    model = db.get(PredictionModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    return model


@router.post("/{model_id}/archive", response_model=ModelSummaryOut)
def archive_model(model_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """封存後不再參與每日選股，但已經開著的持有會維持原狀停在那裡，歷史績效
    也照樣看得到——封存是「停止繼續動作」，不是「刪掉這段歷史」。"""
    model = _get_model(db, model_id)
    model.is_archived = True
    db.commit()
    db.refresh(model)
    stats = summarize_holdings(db, [model.id])
    return _to_summary(model, stats.get(model.id, {}))


@router.post("/{model_id}/unarchive", response_model=ModelSummaryOut)
def unarchive_model(model_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    model = _get_model(db, model_id)
    model.is_archived = False
    db.commit()
    db.refresh(model)
    stats = summarize_holdings(db, [model.id])
    return _to_summary(model, stats.get(model.id, {}))
