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

import numpy as np
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models import PredictionModel
from app.services.matching import TAIPEI_TZ
from app.services.ml import artifacts
from app.services.ml.backtest_eval import run_backtest
from app.services.ml.dataset import (
    apply_scaler,
    attach_labels,
    fit_scaler,
    fit_scaler_sequences,
    split_by_date,
    to_matrix,
)
from app.services.ml.features import WARMUP_BARS, build_feature_rows
from app.services.ml.selection import ModelBundle
from app.services.ml.train import SEQUENCE_MODEL_TYPES, train_dual_task

logger = logging.getLogger(__name__)

_executor: ProcessPoolExecutor | None = None

# 暖身需要的日曆天數：60 個交易日約等於 90 個日曆天，多抓一些緩衝
WARMUP_CALENDAR_DAYS = WARMUP_BARS * 2

# 交易日換算成日曆天的粗略倍數（一週 5 個交易日 / 7 天），再多留一點緩衝
TRADING_DAY_TO_CALENDAR = 1.6


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


def _sequence_length_for(model: PredictionModel) -> int | None:
    """序列模型才有視窗長度；其他類型一律 None（下游用它來判斷要走哪條路）。"""
    if model.model_type not in SEQUENCE_MODEL_TYPES:
        return None
    from app.services.ml.sequences import DEFAULT_SEQUENCE_LENGTH

    config = model.network_config or {}
    return int(config.get("sequence_length") or DEFAULT_SEQUENCE_LENGTH)


def _labels(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """序列模型的 X 由 stack_sequences 組，但 label 還是逐列來的，另外抽出來。"""
    y_reg = np.array([row["future_return_percent"] for row in rows], dtype=np.float64)
    y_clf = np.array([row["label"] for row in rows], dtype=np.int64)
    return y_reg, y_clf


def _progress_writer(db: Session, model_id: int):
    """回傳一個把訓練進度寫進資料庫的函式。

    訓練跑在獨立的 process 裡，跟 API 之間沒有共享記憶體，資料庫是唯一的
    溝通管道。每個 epoch commit 一次聽起來很多，但相對於一輪動輒數秒的 GPU
    運算完全可以忽略。

    寫進度失敗一律吞掉：進度只是附加資訊，不值得讓一次訓練因此中斷。
    """

    def write(phase: str, detail: dict | None = None) -> None:
        try:
            model = db.get(PredictionModel, model_id)
            if model is None:
                return
            model.training_progress = {
                "phase": phase,
                "updated_at": datetime.now(TAIPEI_TZ).isoformat(),
                **(detail or {}),
            }
            flag_modified(model, "training_progress")
            db.commit()
        except Exception:
            logger.warning("寫入模型 %d 的訓練進度失敗", model_id, exc_info=True)
            db.rollback()

    return write


def _train_sync(model_id: int) -> dict:
    """真正做事的地方，跑在獨立的 process 裡，所以自己開資料庫連線。"""
    db: Session = SessionLocal()
    started = time.perf_counter()
    try:
        model = db.get(PredictionModel, model_id)
        if model is None:
            raise ValueError(f"找不到模型 {model_id}")

        model.status = "training"
        model.training_progress = None
        db.commit()

        progress = _progress_writer(db, model_id)
        progress("preparing")

        feature_keys = list(model.feature_config)
        sequence_length = _sequence_length_for(model)

        # 序列模型要能回頭看 T 天，所以特徵列得從訓練起始日之前就開始產出——
        # 不然訓練期最前面那 T-1 天會因為湊不出完整視窗而整批被丟掉。
        feature_start = model.train_start
        if sequence_length:
            feature_start -= timedelta(days=int(sequence_length * TRADING_DAY_TO_CALENDAR) + 7)

        fetch_start = feature_start - timedelta(days=WARMUP_CALENDAR_DAYS)
        rows, bars_by_code = build_feature_rows(db, fetch_start, model.test_end, feature_start)

        if sequence_length:
            # 索引要在切分之前、對「完整的」特徵列做，早於訓練起始日的那些列
            # 不會成為訓練目標，但要留著當歷史用
            from app.services.ml.sequences import index_feature_rows

            index_feature_rows(rows, feature_keys)

        # 超額報酬要用大盤水位，跟特徵那邊算的是同一份等權合成指數
        from app.services.ml.features import build_market_series, market_levels

        levels = market_levels(build_market_series(bars_by_code)) if model.label_mode == "excess" else None
        labeled = attach_labels(
            rows,
            bars_by_code,
            model.n_days,
            model.threshold_percent,
            label_mode=model.label_mode,
            market_levels=levels,
        )
        if not labeled:
            raise ValueError("這段期間沒有足夠的本地日K資料可以組出訓練樣本，請先回補更多歷史或調整日期區間")

        train_rows = split_by_date(labeled, model.train_start, model.train_end)
        validation_rows = split_by_date(labeled, model.validation_start, model.validation_end)
        test_rows = split_by_date(labeled, model.test_start, model.test_end)

        if sequence_length:
            from app.services.ml.sequences import filter_rows_with_history

            train_rows = filter_rows_with_history(train_rows, sequence_length)
            validation_rows = filter_rows_with_history(validation_rows, sequence_length)
            test_rows = filter_rows_with_history(test_rows, sequence_length)

        if not train_rows:
            raise ValueError("訓練區間沒有任何樣本，請往前調整訓練起始日或先回補更多歷史")
        if not validation_rows:
            raise ValueError("驗證區間沒有任何樣本，請調整驗證日期區間")
        if not test_rows:
            raise ValueError("測試區間沒有任何樣本，請調整測試日期區間")

        y_train_reg, y_train_clf = _labels(train_rows)
        y_validation_reg, y_validation_clf = _labels(validation_rows)

        # 標準化參數只用訓練集算，再套用到驗證/測試，避免測試集的分布洩漏進訓練
        if sequence_length:
            from app.services.ml.sequences import stack_sequences

            x_train_raw = stack_sequences(train_rows, sequence_length)
            x_validation_raw = stack_sequences(validation_rows, sequence_length)
            scaler_mean, scaler_std = fit_scaler_sequences(x_train_raw)
        else:
            x_train_raw, y_train_reg, y_train_clf = to_matrix(train_rows, feature_keys)
            x_validation_raw, y_validation_reg, y_validation_clf = to_matrix(validation_rows, feature_keys)
            scaler_mean, scaler_std = fit_scaler(x_train_raw)

        x_train = apply_scaler(x_train_raw, scaler_mean, scaler_std)
        x_validation = apply_scaler(x_validation_raw, scaler_mean, scaler_std)

        progress("training", {"epoch": 0, "total_epochs": (model.network_config or {}).get("epochs")})
        regressor, classifier, metrics = train_dual_task(
            model.model_type,
            feature_keys,
            x_train,
            y_train_reg,
            y_train_clf,
            x_validation,
            y_validation_reg,
            y_validation_clf,
            network_config=model.network_config,
            tree_config=model.tree_config,
            on_epoch_end=lambda info: progress("training", info),
        )

        artifact_path = artifacts.save_bundle(
            model.id, regressor, classifier, feature_keys, scaler_mean, scaler_std, sequence_length
        )
        bundle = ModelBundle(
            regressor=regressor,
            classifier=classifier,
            feature_keys=feature_keys,
            scaler_mean=scaler_mean,
            scaler_std=scaler_std,
            sequence_length=sequence_length,
        )

        from app.services.ml.train import build_data_warnings, evaluate

        if sequence_length:
            from app.services.ml.sequences import stack_sequences

            y_test_reg, y_test_clf = _labels(test_rows)
            x_test_raw = stack_sequences(test_rows, sequence_length)
        else:
            x_test_raw, y_test_reg, y_test_clf = to_matrix(test_rows, feature_keys)
        x_test = apply_scaler(x_test_raw, scaler_mean, scaler_std)
        metrics["test"] = evaluate(regressor, classifier, x_test, y_test_reg, y_test_clf)
        del x_train, x_validation, x_test, x_train_raw, x_validation_raw, x_test_raw

        progress("backtesting")
        metrics["backtest"] = run_backtest(db, model, bundle, test_rows, bars_by_code)
        metrics["warnings"] = build_data_warnings(
            metrics["train"], metrics["validation"], metrics["test"], metrics.get("network")
        )

        model.metrics = metrics
        model.model_artifact_path = artifact_path
        model.status = "completed"
        model.training_progress = None  # 完成後清掉，狀態與 metrics 才是唯一真相
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
