"""訓練的完整流程與背景執行。

訓練是 CPU 密集的同步運算，直接在 FastAPI 的 event loop 裡跑會把整個服務卡住
（所有使用者的請求都會停住），所以丟到 ProcessPoolExecutor 執行。只開一個
worker：這台機器同時跑訓練跟正常服務，多開只會互相搶 CPU 跟記憶體。

`prediction_models.status` 本身就是工作狀態（queued → training → completed/failed），
admin 頁面輪詢那個欄位就知道進度，不需要另外一張 job 表。
"""

import asyncio
import logging
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import PredictionModel
from app.services.matching import TAIPEI_TZ
from app.services.ml import artifacts
from app.services.ml.backtest_eval import run_backtest
from app.services.ml.dataset import apply_scaler, attach_labels, fit_scaler, split_by_date, to_matrix
from app.services.ml.features import WARMUP_BARS, build_feature_rows
from app.services.ml.selection import ModelBundle
from app.services.ml.train import train_dual_task

logger = logging.getLogger(__name__)

_executor: ProcessPoolExecutor | None = None

# 暖身需要的日曆天數：60 個交易日約等於 90 個日曆天，多抓一些緩衝
WARMUP_CALENDAR_DAYS = WARMUP_BARS * 2


def _init_worker() -> None:
    """子 process 是用 fork 產生的，會連同父 process 連線池裡「已經開著的」
    資料庫 socket 一起繼承過來。父子兩邊同時對同一條連線讀寫，libpq 的狀態會
    直接錯亂（實測會噴 PGRES_TUPLES_OK and no message from the libpq）。

    dispose(close=False) 是 SQLAlchemy 對 fork 的標準處置：只丟掉這邊的引用、
    不去關閉那些其實屬於父 process 的連線，之後子 process 會自己開新的。"""
    from app.database import engine

    engine.dispose(close=False)


def get_executor() -> ProcessPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ProcessPoolExecutor(max_workers=1, initializer=_init_worker)
    return _executor


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def _train_sync(model_id: int) -> dict:
    """真正做事的地方，跑在獨立的 process 裡，所以自己開資料庫連線。"""
    db: Session = SessionLocal()
    started = time.perf_counter()
    try:
        model = db.get(PredictionModel, model_id)
        if model is None:
            raise ValueError(f"找不到模型 {model_id}")

        model.status = "training"
        db.commit()

        fetch_start = model.train_start - timedelta(days=WARMUP_CALENDAR_DAYS)
        rows, bars_by_code = build_feature_rows(db, fetch_start, model.test_end, model.train_start)
        labeled = attach_labels(rows, bars_by_code, model.n_days, model.threshold_percent)
        if not labeled:
            raise ValueError("這段期間沒有足夠的本地日K資料可以組出訓練樣本，請先回補更多歷史或調整日期區間")

        feature_keys = list(model.feature_config)
        train_rows = split_by_date(labeled, model.train_start, model.train_end)
        validation_rows = split_by_date(labeled, model.validation_start, model.validation_end)
        test_rows = split_by_date(labeled, model.test_start, model.test_end)

        if not train_rows:
            raise ValueError("訓練區間沒有任何樣本，請往前調整訓練起始日或先回補更多歷史")
        if not validation_rows:
            raise ValueError("驗證區間沒有任何樣本，請調整驗證日期區間")
        if not test_rows:
            raise ValueError("測試區間沒有任何樣本，請調整測試日期區間")

        x_train_raw, y_train_reg, y_train_clf = to_matrix(train_rows, feature_keys)
        x_validation_raw, y_validation_reg, y_validation_clf = to_matrix(validation_rows, feature_keys)

        # 標準化參數只用訓練集算，再套用到驗證/測試，避免測試集的分布洩漏進訓練
        scaler_mean, scaler_std = fit_scaler(x_train_raw)
        x_train = apply_scaler(x_train_raw, scaler_mean, scaler_std)
        x_validation = apply_scaler(x_validation_raw, scaler_mean, scaler_std)

        regressor, classifier, metrics = train_dual_task(
            model.model_type,
            feature_keys,
            x_train,
            y_train_reg,
            y_train_clf,
            x_validation,
            y_validation_reg,
            y_validation_clf,
        )

        artifact_path = artifacts.save_bundle(
            model.id, regressor, classifier, feature_keys, scaler_mean, scaler_std
        )
        bundle = ModelBundle(
            regressor=regressor,
            classifier=classifier,
            feature_keys=feature_keys,
            scaler_mean=scaler_mean,
            scaler_std=scaler_std,
        )

        from app.services.ml.train import build_data_warnings, evaluate

        x_test_raw, y_test_reg, y_test_clf = to_matrix(test_rows, feature_keys)
        x_test = apply_scaler(x_test_raw, scaler_mean, scaler_std)
        metrics["test"] = evaluate(regressor, classifier, x_test, y_test_reg, y_test_clf)
        metrics["backtest"] = run_backtest(db, model, bundle, test_rows, bars_by_code)
        metrics["warnings"] = build_data_warnings(metrics["train"], metrics["validation"], metrics["test"])

        model.metrics = metrics
        model.model_artifact_path = artifact_path
        model.status = "completed"
        model.trained_at = datetime.now(TAIPEI_TZ)
        model.training_duration_seconds = time.perf_counter() - started
        db.commit()
        logger.info("模型 %d 訓練完成，耗時 %.1f 秒", model_id, model.training_duration_seconds)
        return {"status": "completed", "model_id": model_id}

    except Exception as e:
        logger.exception("模型 %d 訓練失敗", model_id)
        db.rollback()
        model = db.get(PredictionModel, model_id)
        if model is not None:
            model.status = "failed"
            model.error_message = str(e)[:500]
            model.training_duration_seconds = time.perf_counter() - started
            db.commit()
        return {"status": "failed", "model_id": model_id, "error": str(e)}
    finally:
        db.close()


async def run_training_job(model_id: int) -> None:
    """把訓練丟到 process pool，不阻塞 event loop。"""
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(get_executor(), _train_sync, model_id)
    except Exception:
        logger.exception("訓練工作 %d 執行時發生非預期錯誤", model_id)


def suggest_split_dates(latest_date: date | None) -> dict[str, date]:
    """依「本地資料最新日期」往回推算建議的六個切分界線（訓練 3 個月 / 驗證
    2 個月 / 測試 1 個月）。這只是表單的預設值，admin 可以自己改。"""
    end = latest_date or date.today()
    test_start = end - timedelta(days=30)
    validation_end = test_start - timedelta(days=1)
    validation_start = validation_end - timedelta(days=60)
    train_end = validation_start - timedelta(days=1)
    train_start = train_end - timedelta(days=90)
    return {
        "train_start": train_start,
        "train_end": train_end,
        "validation_start": validation_start,
        "validation_end": validation_end,
        "test_start": test_start,
        "test_end": end,
    }
