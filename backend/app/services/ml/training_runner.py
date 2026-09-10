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
from app.services.ml.walk_forward import (
    DEFAULT_STEP_MONTHS,
    DEFAULT_TEST_MONTHS,
    DEFAULT_TRAIN_MONTHS,
    DEFAULT_VALIDATION_MONTHS,
    Fold,
    generate_folds,
    summarize_folds,
)

VALIDATION_SINGLE = "single"
VALIDATION_WALK_FORWARD = "walk_forward"

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


def _prepare_rows(db: Session, model: PredictionModel, feature_keys: list[str], sequence_length: int | None):
    """把整段期間的特徵與 label 一次算好。

    走 walk-forward 時這一步刻意只做一次：每一折的差別只在「拿哪一段當訓練、
    哪一段當測試」，特徵本身完全相同。每折各算一次會把一次執行從幾分鐘拖成
    半小時，而且算出來的東西一模一樣。
    """
    feature_start = model.train_start
    if sequence_length:
        # 序列模型要能回頭看 T 天，特徵列得從訓練起始日之前就開始產出
        feature_start -= timedelta(days=int(sequence_length * TRADING_DAY_TO_CALENDAR) + 7)

    fetch_start = feature_start - timedelta(days=WARMUP_CALENDAR_DAYS)
    rows, bars_by_code = build_feature_rows(db, fetch_start, model.test_end, feature_start)

    if sequence_length:
        from app.services.ml.sequences import index_feature_rows

        index_feature_rows(rows, feature_keys)

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
    return labeled, bars_by_code


def _split_fold(labeled: list[dict], fold: Fold, sequence_length: int | None):
    """依一折的六個日期界線切出三段，並回報哪一段是空的。"""
    train_rows = split_by_date(labeled, fold.train_start, fold.train_end)
    validation_rows = split_by_date(labeled, fold.validation_start, fold.validation_end)
    test_rows = split_by_date(labeled, fold.test_start, fold.test_end)

    if sequence_length:
        from app.services.ml.sequences import filter_rows_with_history

        train_rows = filter_rows_with_history(train_rows, sequence_length)
        validation_rows = filter_rows_with_history(validation_rows, sequence_length)
        test_rows = filter_rows_with_history(test_rows, sequence_length)

    empty = [
        name
        for name, rows in (("訓練", train_rows), ("驗證", validation_rows), ("測試", test_rows))
        if not rows
    ]
    return train_rows, validation_rows, test_rows, empty


def _build_matrices(rows: list[dict], feature_keys: list[str], sequence_length: int | None):
    """回傳 (X_raw, y_迴歸, y_分類)。序列模型的 X 多一個時間維度。"""
    if sequence_length:
        from app.services.ml.sequences import stack_sequences

        y_reg, y_clf = _labels(rows)
        return stack_sequences(rows, sequence_length), y_reg, y_clf
    return to_matrix(rows, feature_keys)


def _train_one_fold(
    model: PredictionModel,
    feature_keys: list[str],
    sequence_length: int | None,
    labeled: list[dict],
    fold: Fold,
    progress,
    fold_note: dict,
):
    """訓練一折並回傳 (迴歸模型, 分類模型, metrics, 標準化參數, 測試列)。"""
    train_rows, validation_rows, test_rows, empty = _split_fold(labeled, fold, sequence_length)
    if empty:
        raise ValueError(f"第 {fold.index} 折的{'、'.join(empty)}區間沒有任何樣本，請調整日期或先回補更多歷史")

    x_train_raw, y_train_reg, y_train_clf = _build_matrices(train_rows, feature_keys, sequence_length)
    x_validation_raw, y_validation_reg, y_validation_clf = _build_matrices(
        validation_rows, feature_keys, sequence_length
    )

    # 標準化參數只用這一折的訓練集算。折與折之間不共用——共用等於讓後面的
    # 折看到前面折的分布，正是 walk-forward 要避免的事
    fit = fit_scaler_sequences if sequence_length else fit_scaler
    scaler_mean, scaler_std = fit(x_train_raw)
    x_train = apply_scaler(x_train_raw, scaler_mean, scaler_std)
    x_validation = apply_scaler(x_validation_raw, scaler_mean, scaler_std)

    progress("training", {**fold_note, "epoch": 0, "total_epochs": (model.network_config or {}).get("epochs")})
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
        on_epoch_end=lambda info: progress("training", {**fold_note, **info}),
    )

    from app.services.ml.train import evaluate

    x_test_raw, y_test_reg, y_test_clf = _build_matrices(test_rows, feature_keys, sequence_length)
    x_test = apply_scaler(x_test_raw, scaler_mean, scaler_std)
    metrics["test"] = evaluate(regressor, classifier, x_test, y_test_reg, y_test_clf)
    metrics["fold"] = fold.as_dict()

    del x_train, x_validation, x_test, x_train_raw, x_validation_raw, x_test_raw
    return regressor, classifier, metrics, (scaler_mean, scaler_std), test_rows


def _folds_for(model: PredictionModel) -> list[Fold]:
    """單次切分就是「只有一折」，走的是同一條程式碼路徑。"""
    if model.validation_mode != VALIDATION_WALK_FORWARD:
        return [
            Fold(
                index=1,
                train_start=model.train_start,
                train_end=model.train_end,
                validation_start=model.validation_start,
                validation_end=model.validation_end,
                test_start=model.test_start,
                test_end=model.test_end,
            )
        ]

    config = model.walk_forward_config or {}
    folds = generate_folds(
        model.train_start,
        model.test_end,
        train_months=int(config.get("train_months", DEFAULT_TRAIN_MONTHS)),
        validation_months=int(config.get("validation_months", DEFAULT_VALIDATION_MONTHS)),
        test_months=int(config.get("test_months", DEFAULT_TEST_MONTHS)),
        step_months=int(config.get("step_months", DEFAULT_STEP_MONTHS)),
    )
    if not folds:
        raise ValueError(
            "這段期間排不下任何一折。整段長度至少要是「訓練 + 驗證 + 測試」的月數總和，"
            "請把起訖日期拉長或把各段月數調小"
        )
    return folds


def _walk_forward_warnings(summary: dict) -> list[str]:
    """滾動驗證才問得出來的問題：這個數字到底站不站得住腳。"""
    warnings: list[str] = []
    stats = summary.get("test_rank_ic")
    if not stats:
        return warnings

    mean, std = stats["mean"], stats["std"]
    positive, count = stats["positive_folds"], stats["count"]

    # 標準差比平均還大，代表折與折之間的差距完全蓋過了平均值本身。
    # 這正是單次切分看不出來、但會讓人誤以為模型有效的情況。
    if std > abs(mean):
        warnings.append(
            f"測試 Rank IC 的折間標準差（{std:.3f}）大於平均值（{mean:+.3f}），"
            f"{count} 折裡只有 {positive} 折是正的。這個平均值站不住腳——"
            "換一段測試期就可能翻正負號，不能當作模型有效的證據。"
        )
    elif positive == count and mean > 0:
        warnings.append(
            f"{count} 折的測試 Rank IC 全部為正（平均 {mean:+.3f}、標準差 {std:.3f}）。"
            "這是目前為止最接近「穩定訊號」的結果，但折與折之間的訓練期高度重疊，"
            "仍不等於獨立的多次驗證。"
        )
    return warnings


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
        labeled, bars_by_code = _prepare_rows(db, model, feature_keys, sequence_length)
        folds = _folds_for(model)

        fold_metrics: list[dict] = []
        last = None
        for fold in folds:
            note = {"fold": fold.index, "total_folds": len(folds)} if len(folds) > 1 else {}
            outcome = _train_one_fold(
                model, feature_keys, sequence_length, labeled, fold, progress, note
            )
            fold_metrics.append(outcome[2])
            last = outcome
            logger.info(
                "模型 %d 第 %d/%d 折完成：測試 RankIC=%s",
                model_id,
                fold.index,
                len(folds),
                outcome[2]["test"]["rank_ic"],
            )

        regressor, classifier, metrics, (scaler_mean, scaler_std), test_rows = last

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

        from app.services.ml.train import build_data_warnings

        # 回測只跑最後一折。它是用最近的資料訓練的，也就是真的會被拿去上線的
        # 那一個；其餘折的價值在於 Rank IC 的穩定度，不需要各自跑一次回測
        # （每折回測要多花兩分半，而它回答的不是「這個改動有沒有效」）。
        progress("backtesting")
        metrics["backtest"] = run_backtest(db, model, bundle, test_rows, bars_by_code)
        metrics["warnings"] = build_data_warnings(
            metrics["train"], metrics["validation"], metrics["test"], metrics.get("network")
        )

        if len(folds) > 1:
            metrics["folds"] = [
                {"fold": m["fold"], "train": m["train"], "validation": m["validation"], "test": m["test"]}
                for m in fold_metrics
            ]
            metrics["walk_forward"] = summarize_folds(fold_metrics)
            metrics["warnings"] = metrics["warnings"] + _walk_forward_warnings(metrics["walk_forward"])

        model.metrics = metrics
        model.model_artifact_path = artifact_path
        model.status = "completed"
        model.training_progress = None  # 完成後清掉，狀態與 metrics 才是唯一真相
        model.trained_at = datetime.now(TAIPEI_TZ)
        model.training_duration_seconds = time.perf_counter() - started
        db.commit()
        logger.info(
            "模型 %d 訓練完成（%d 折），耗時 %.1f 秒", model_id, len(folds), model.training_duration_seconds
        )
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
