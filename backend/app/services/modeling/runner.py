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
from app.services.platform.clock import TAIPEI_TZ
from app.services.modeling import artifacts
from app.services.trading.backtest_eval import run_backtest
from app.services.modeling.labels import (
    EXECUTION_MODES,
    EXECUTION_NEXT_OPEN,
    attach_labels,
    purge_tail,
    split_by_date,
    to_matrix,
)
from app.services.features.transforms import SCALING_RANK, apply_scaler, fit_scaler, fit_scaler_sequences, industry_neutralize, rank_normalize
from app.services.ingest.industry_sync import load_industry_map
from app.services.ingest.universe import load_delisted_codes
from app.services.features.frame import FeatureFrame
from app.services.features.builder import (
    CROSS_SECTION_SKIP_KEYS,
    NEXT_OPEN_ONLY_KEYS,
    WARMUP_BARS,
    build_feature_rows,
)
from app.services.trading.selection import ModelBundle
from app.services.modeling.train import SEQUENCE_MODEL_TYPES, _rank_ic, train_dual_task
from app.services.modeling import cpcv as cpcv_mod
from app.services.modeling.walk_forward import (
    DEFAULT_STEP_MONTHS,
    DEFAULT_TEST_MONTHS,
    DEFAULT_TRAIN_MONTHS,
    DEFAULT_VALIDATION_MONTHS,
    MAX_FOLDS,
    Fold,
    generate_folds,
    summarize_folds,
)

VALIDATION_SINGLE = "single"
VALIDATION_WALK_FORWARD = "walk_forward"

logger = logging.getLogger(__name__)

_executor: ProcessPoolExecutor | None = None

# 已排入但還沒跑完的訓練工作。只是為了不讓 asyncio 把它們 GC 掉——
# 真正的排隊是 executor 的 max_workers=1 在做的
_pending_tasks: set[asyncio.Task] = set()

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
    from app.services.features.sequences import DEFAULT_SEQUENCE_LENGTH

    config = model.network_config or {}
    return int(config.get("sequence_length") or DEFAULT_SEQUENCE_LENGTH)


def _labels(rows: FeatureFrame) -> tuple[np.ndarray, np.ndarray]:
    """序列模型的 X 由 stack_sequences 組，但 label 還是逐列來的，另外抽出來。"""
    return (
        rows.column("future_return_percent").astype(np.float64),
        rows.column("label").astype(np.int64),
    )


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
        from app.services.features.sequences import index_feature_rows

        index_feature_rows(rows, feature_keys)

    from app.services.features.builder import build_market_series, market_levels

    levels = market_levels(build_market_series(bars_by_code)) if model.label_mode == "excess" else None
    labeled = attach_labels(
        rows,
        bars_by_code,
        model.n_days,
        model.threshold_percent,
        label_mode=model.label_mode,
        market_levels=levels,
        execution_mode=model.execution_mode,
        delisted_codes=load_delisted_codes(db),
    )
    if not labeled:
        raise ValueError("這段期間沒有足夠的本地日K資料可以組出訓練樣本，請先回補更多歷史或調整日期區間")

    # 排名只用同一天的橫斷面，不看未來，所以在切分之前做是安全的；
    # 而且必須在切分之前做——每折各自排名的話，同一天的同一檔股票會因為
    # 落在不同折而拿到不同的名次，那是沒有意義的
    if model.feature_scaling == SCALING_RANK:
        labeled = rank_normalize(labeled, feature_keys, skip=set(CROSS_SECTION_SKIP_KEYS))

    # 產業中性化排在排名之後：兩者都是「同一天的橫斷面」運算，先排名再減同業
    # 中位數，得到的是「這檔在同業裡的相對名次」，比直接減原始值穩定
    if model.industry_neutral:
        labeled = industry_neutralize(
            labeled, feature_keys, load_industry_map(db), skip=set(CROSS_SECTION_SKIP_KEYS)
        )

    return labeled, bars_by_code


def _split_fold(
    labeled: FeatureFrame, fold: Fold, sequence_length: int | None, purge_days: int = 0
):
    """依一折的六個日期界線切出三段，並回報哪一段是空的。

    purge_days > 0 時，訓練段與驗證段的**尾端**會各砍掉那麼多個交易日。
    這兩個邊界都需要處理：訓練尾端的標籤會延伸到驗證期，驗證尾端的標籤會
    延伸到測試期——後者對有早停的神經網路特別要緊，因為模型的選擇會間接
    受到測試期資料影響。測試段不砍，它是最後一段，後面沒有東西可洩漏。
    """
    train_rows = purge_tail(split_by_date(labeled, fold.train_start, fold.train_end), purge_days)
    validation_rows = purge_tail(
        split_by_date(labeled, fold.validation_start, fold.validation_end), purge_days
    )
    test_rows = split_by_date(labeled, fold.test_start, fold.test_end)

    if sequence_length:
        from app.services.features.sequences import filter_rows_with_history

        train_rows = filter_rows_with_history(train_rows, sequence_length)
        validation_rows = filter_rows_with_history(validation_rows, sequence_length)
        test_rows = filter_rows_with_history(test_rows, sequence_length)

    empty = [
        name
        for name, rows in (("訓練", train_rows), ("驗證", validation_rows), ("測試", test_rows))
        if not rows
    ]
    return train_rows, validation_rows, test_rows, empty


def _build_matrices(rows: FeatureFrame, feature_keys: list[str], sequence_length: int | None):
    """回傳 (X_raw, y_迴歸, y_分類)。序列模型的 X 多一個時間維度。"""
    if sequence_length:
        from app.services.features.sequences import stack_sequences

        y_reg, y_clf = _labels(rows)
        return stack_sequences(rows, sequence_length), y_reg, y_clf
    return to_matrix(rows, feature_keys)


# label 之外再多空幾個交易日。López de Prado 建議約資料長度的 1%，
# 我們一折的訓練期約 120 個交易日，取 1 天
DEFAULT_EMBARGO_DAYS = 1


def _purge_days_for(model: PredictionModel) -> int:
    """一折的邊界要砍掉幾個交易日 = label 佔用的天數 + embargo。

    label 長度不是選項而是事實：n_days 就是每一筆樣本的答案往後看多遠，
    所以那幾天必然重疊下一段。embargo 才是可調的保守加碼。

    next_open 模式要再多砍一天：那時基準日 D 的樣本是「開盤 D+1 → 開盤
    D+1+n」，實際佔用的區間是 [D+1, D+1+n]，比 close 模式往後多伸一天。
    """
    config = model.walk_forward_config or {}
    embargo = int(config.get("embargo_days", DEFAULT_EMBARGO_DAYS))
    span = int(model.n_days) + (1 if model.execution_mode == EXECUTION_NEXT_OPEN else 0)
    return span + max(embargo, 0)


def _fit_and_evaluate(
    model: PredictionModel,
    feature_keys: list[str],
    sequence_length: int | None,
    train_rows: FeatureFrame,
    validation_rows: FeatureFrame,
    test_rows: FeatureFrame,
    progress,
    fold_note: dict,
):
    """給定已經切好的三段，訓練並評估。

    walk-forward 與 CPCV 只差在「怎麼切」——切完之後的訓練、標準化、評估
    完全一樣，所以抽出來共用，兩邊才不會慢慢長出不一致的行為。

    回傳 (迴歸模型, 分類模型, metrics, 標準化參數, 測試列)。
    """
    x_train_raw, y_train_reg, y_train_clf = _build_matrices(train_rows, feature_keys, sequence_length)
    x_validation_raw, y_validation_reg, y_validation_clf = _build_matrices(
        validation_rows, feature_keys, sequence_length
    )

    # 標準化參數只用這一折的訓練集算。折與折之間不共用——共用等於讓後面的
    # 折看到前面折的分布，正是這類驗證要避免的事
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

    from app.services.modeling.train import evaluate

    x_test_raw, y_test_reg, y_test_clf = _build_matrices(test_rows, feature_keys, sequence_length)
    x_test = apply_scaler(x_test_raw, scaler_mean, scaler_std)
    metrics["test"] = evaluate(regressor, classifier, x_test, y_test_reg, y_test_clf)

    del x_train, x_validation, x_test, x_train_raw, x_validation_raw, x_test_raw
    return regressor, classifier, metrics, (scaler_mean, scaler_std), test_rows


def _train_one_fold(
    model: PredictionModel,
    feature_keys: list[str],
    sequence_length: int | None,
    labeled: FeatureFrame,
    fold: Fold,
    progress,
    fold_note: dict,
):
    """切出一折再訓練。"""
    purge_days = _purge_days_for(model)
    train_rows, validation_rows, test_rows, empty = _split_fold(
        labeled, fold, sequence_length, purge_days
    )
    if empty:
        raise ValueError(f"第 {fold.index} 折的{'、'.join(empty)}區間沒有任何樣本，請調整日期或先回補更多歷史")

    logger.info(
        "第 %d 折：訓練 %d 列、驗證 %d 列、測試 %d 列（訓練與驗證尾端各淨化 %d 個交易日）",
        fold.index, len(train_rows), len(validation_rows), len(test_rows), purge_days,
    )
    outcome = _fit_and_evaluate(
        model, feature_keys, sequence_length, train_rows, validation_rows, test_rows,
        progress, fold_note,
    )
    outcome[2]["fold"] = fold.as_dict()
    return outcome


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
        max_folds=int(config.get("max_folds", MAX_FOLDS)),
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


VALIDATION_CPCV = "cpcv"


def _train_cpcv(model, feature_keys, sequence_length, labeled, progress) -> tuple:
    """跑 CPCV：窮舉 C(N,k) 個組合，再把結果拼成多條路徑。

    跟 walk-forward 的差別不只是切法。每個組合的訓練集是**好幾組的聯集**，
    而且測試組可能夾在訓練資料中間——所以淨化要雙側做，這在 cpcv.purged_train_mask
    裡處理。

    回傳 (最後一個組合的訓練結果, 每組合的 metrics, 路徑彙總)。挑「最後一個」
    當成要存檔的模型純粹是要有個東西可存；CPCV 的產出本來就是分布而不是
    單一模型，真要上線應該用 walk-forward 的最後一折。
    """
    config = model.walk_forward_config or {}
    n_groups = int(config.get("cpcv_groups", cpcv_mod.DEFAULT_GROUPS))
    k = int(config.get("cpcv_test_groups", cpcv_mod.DEFAULT_TEST_GROUPS))
    purge_days = int(model.n_days)
    embargo_days = int(config.get("embargo_days", DEFAULT_EMBARGO_DAYS))

    days = labeled.unique_dates()
    groups = cpcv_mod.make_groups(days, n_groups)
    splits = cpcv_mod.generate_splits(n_groups, k)
    phi = cpcv_mod.path_count(n_groups, k)
    logger.info(
        "CPCV：%d 組、每次測 %d 組 → %d 個組合、%d 條路徑（淨化 %d 天、禁制 %d 天）",
        n_groups, k, len(splits), phi, purge_days, embargo_days,
    )

    unique_days = np.unique(labeled.dates)
    dates = labeled.dates
    by_split: dict[int, dict] = {}
    last = None

    for split in splits:
        note = {"fold": split.index, "total_folds": len(splits)}
        train_mask = cpcv_mod.purged_train_mask(
            dates, groups, split.train_groups, split.test_groups,
            unique_days, purge_days, embargo_days,
        )
        # 驗證組也要跟測試組保持距離，理由跟訓練組一樣
        val_mask = cpcv_mod.purged_train_mask(
            dates, groups, (split.validation_group,), split.test_groups,
            unique_days, purge_days, embargo_days,
        )
        test_mask = cpcv_mod.group_mask(dates, groups, split.test_groups)

        train_rows = labeled.mask(train_mask)
        validation_rows = labeled.mask(val_mask)
        test_rows = labeled.mask(test_mask)
        if sequence_length:
            from app.services.features.sequences import filter_rows_with_history

            train_rows = filter_rows_with_history(train_rows, sequence_length)
            validation_rows = filter_rows_with_history(validation_rows, sequence_length)
            test_rows = filter_rows_with_history(test_rows, sequence_length)

        empty = [n for n, r in (("訓練", train_rows), ("驗證", validation_rows), ("測試", test_rows)) if not r]
        if empty:
            raise ValueError(f"CPCV 組合 {split.index} 的{'、'.join(empty)}沒有任何樣本，請調小組數")

        outcome = _fit_and_evaluate(
            model, feature_keys, sequence_length, train_rows, validation_rows, test_rows,
            progress, note,
        )
        metrics = outcome[2]
        metrics["cpcv_split"] = split.as_dict()
        # 逐組的分數：路徑要靠這個拼
        metrics["group_rank_ic"] = {
            str(g): _rank_ic_for_group(outcome, labeled, groups, g, feature_keys, sequence_length)
            for g in split.test_groups
        }
        by_split[split.index] = metrics
        last = outcome
        logger.info(
            "模型 %s CPCV 組合 %d/%d 完成：測試 RankIC=%s",
            model.id, split.index, len(splits), metrics["test"]["rank_ic"],
        )

    # ── 拼路徑 ──
    paths = cpcv_mod.assign_paths(splits, n_groups)
    path_scores = []
    for assignment in paths:
        per_group = [
            by_split[combo]["group_rank_ic"].get(str(g))
            for g, combo in assignment.items()
        ]
        vals = [v for v in per_group if v is not None]
        if vals:
            path_scores.append(float(np.mean(vals)))

    summary = {
        "groups": [g.as_dict() for g in groups],
        "n_groups": n_groups,
        "test_groups": k,
        "combination_count": len(splits),
        "path_rank_ic": cpcv_mod.summarize_paths(path_scores),
        "path_scores": [round(x, 6) for x in path_scores],
    }
    return last, list(by_split.values()), summary


def _rank_ic_for_group(outcome, labeled, groups, g, feature_keys, sequence_length) -> float | None:
    """單獨一組的 Rank IC。路徑是由「不同組合測同一組」的結果拼起來的，
    所以要的是逐組分數，而不是整個測試集（k 組合在一起）的分數。"""
    regressor, classifier, _, (mean, std), _ = outcome
    rows = labeled.mask(cpcv_mod.group_mask(labeled.dates, groups, g))
    if sequence_length:
        from app.services.features.sequences import filter_rows_with_history

        rows = filter_rows_with_history(rows, sequence_length)
    if len(rows) < 10:
        return None
    x_raw, y_reg, _ = _build_matrices(rows, feature_keys, sequence_length)
    x = apply_scaler(x_raw, mean, std)
    pred = np.asarray(regressor.predict(x), dtype=float)
    return _rank_ic(pred, y_reg)


def _cpcv_warnings(summary: dict) -> list[str]:
    """CPCV 才問得出來的問題：這個 edge 是不是只在某一條歷史上成立。"""
    stats = summary.get("path_rank_ic") or {}
    if not stats:
        return []
    mean, std = stats["mean"], stats["std"]
    positive, count = stats["positive_paths"], stats["count"]
    warnings = [
        f"CPCV 拼出 {count} 條路徑（{summary['n_groups']} 組、每次測 "
        f"{summary['test_groups']} 組、共 {summary['combination_count']} 個組合），"
        f"路徑 Rank IC 平均 {mean:+.4f}、標準差 {std:.4f}，{positive}/{count} 條為正。"
    ]
    if positive < count:
        warnings.append(
            f"有 {count - positive} 條路徑的 Rank IC 是負的。同一組設定在不同的"
            "訓練/測試組合下會翻正負號，代表這個 edge 相當程度取決於「剛好用了"
            "哪一段資料訓練」，不是穩定的預測能力。"
        )
    if std > abs(mean):
        warnings.append(
            f"路徑間的標準差（{std:.4f}）大於平均值（{mean:+.4f}）。這比"
            "walk-forward 的折間標準差更值得擔心——後者混著不同市況的影響，"
            "而路徑之間測的是同一段歷史，差異只來自訓練組合。"
        )
    warnings.append(
        "注意 CPCV 的訓練集會包含測試期之後的資料，所以它**不是**在模擬實際"
        "上線的樣子。它回答的是「這個 edge 有多可能只是運氣」，部署前的績效"
        "估計仍然要看 walk-forward。"
    )
    return warnings


def validate_execution_mode(execution_mode: str, feature_keys: list[str]) -> None:
    """成交模式與特徵集必須相容，不相容就直接讓訓練失敗。

    隔夜特徵（台指期夜盤、美股、ADR）裝的是基準日收盤「之後」那一晚的事。
    在 close 模式（收盤決策、收盤成交）下，成交發生在那一晚之前，所以那些
    欄位是不折不扣的 look-ahead：模型會學到一個上線時根本取不到的訊號，
    回測漂亮、實際無效。

    這裡刻意用例外而不是「自動把那幾欄拿掉」。靜默降級的話，使用者會以為
    自己測的是隔夜特徵、實際上測的是別的東西，而那個誤會不會有任何跡象。
    """
    if execution_mode not in EXECUTION_MODES:
        raise ValueError(f"不認得的成交模式：{execution_mode}")
    if execution_mode == EXECUTION_NEXT_OPEN:
        return
    leaking = [k for k in feature_keys if k in set(NEXT_OPEN_ONLY_KEYS)]
    if leaking:
        raise ValueError(
            "隔夜特徵只能搭配「盤前決策、開盤成交」（next_open）。"
            "收盤成交模式下，這些欄位描述的是成交之後才發生的事，會造成 look-ahead："
            + "、".join(leaking)
        )


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
        validate_execution_mode(model.execution_mode, feature_keys)
        sequence_length = _sequence_length_for(model)
        labeled, bars_by_code = _prepare_rows(db, model, feature_keys, sequence_length)

        cpcv_summary = None
        if model.validation_mode == VALIDATION_CPCV:
            last, fold_metrics, cpcv_summary = _train_cpcv(
                model, feature_keys, sequence_length, labeled, progress
            )
            folds = []
        else:
            folds = _folds_for(model)
            fold_metrics, last = [], None
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
            model.id,
            regressor,
            classifier,
            feature_keys,
            scaler_mean,
            scaler_std,
            sequence_length,
            model.feature_scaling,
            model.industry_neutral,
        )
        bundle = ModelBundle(
            regressor=regressor,
            classifier=classifier,
            feature_keys=feature_keys,
            scaler_mean=scaler_mean,
            scaler_std=scaler_std,
            sequence_length=sequence_length,
            feature_scaling=model.feature_scaling,
            industry_neutral=model.industry_neutral,
        )

        from app.services.modeling.train import build_data_warnings

        # 回測只跑最後一折。它是用最近的資料訓練的，也就是真的會被拿去上線的
        # 那一個；其餘折的價值在於 Rank IC 的穩定度，不需要各自跑一次回測
        # （每折回測要多花兩分半，而它回答的不是「這個改動有沒有效」）。
        progress("backtesting")
        metrics["backtest"] = run_backtest(db, model, bundle, test_rows, bars_by_code)
        metrics["warnings"] = build_data_warnings(
            metrics["train"], metrics["validation"], metrics["test"], metrics.get("network")
        )

        if cpcv_summary is not None:
            metrics["cpcv"] = cpcv_summary
            metrics["folds"] = [
                {"fold": m["cpcv_split"], "train": m["train"], "validation": m["validation"], "test": m["test"]}
                for m in fold_metrics
            ]
            metrics["warnings"] = metrics["warnings"] + _cpcv_warnings(cpcv_summary)
        elif len(folds) > 1:
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


def enqueue_training(model_id: int) -> None:
    """排入訓練佇列。

    真正的序列化是 executor 的 max_workers=1 做的——同時送進來十筆，也只會有
    一筆在跑，其餘的 future 在 executor 裡排隊，`status` 要等輪到它、進了
    worker 才會從 queued 變成 training。所以佇列深度直接反映在 status 上，
    不需要另外維護一份狀態。

    這裡唯一多做的事是**把 task 的參照留住**。asyncio 只持有 task 的弱參照，
    create_task 的回傳值沒人接的話，任務可能在被排到之前就被 GC 掉——佇列愈長
    愈容易踩到，而且失敗時是無聲的。
    """
    task = asyncio.create_task(run_training_job(model_id))
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)
    logger.info("模型 %d 排入訓練佇列（目前佇列中 %d 筆）", model_id, len(_pending_tasks))


def recover_orphaned_jobs(db: Session) -> dict:
    """後端重啟時處理上一輪留下來的工作。

    重啟會把 process pool 連同裡面跑到一半的訓練一起帶走，但資料庫那一列還停在
    training／queued，之後永遠不會有人去動它。兩種狀態要分開處理：

    - training：已經跑掉一部分，沒有辦法接續（中間狀態全在那個 process 裡），
      標成 failed 讓它能被刪掉，而不是留一筆看起來還在跑的殭屍。
    - queued：還沒開始，重新排進佇列就好，沒有任何東西遺失。
    """
    interrupted = db.query(PredictionModel).filter(PredictionModel.status == "training").all()
    for model in interrupted:
        model.status = "failed"
        model.training_progress = None
        model.error_message = "後端在訓練途中重新啟動，這次訓練已中斷（可以直接刪除這個版本再訓練一次）"
    waiting = db.query(PredictionModel).filter(PredictionModel.status == "queued").all()
    db.commit()

    for model in waiting:
        enqueue_training(model.id)

    if interrupted or waiting:
        logger.warning(
            "recover_orphaned_jobs: %d 筆訓練中被標成失敗、%d 筆重新排入佇列",
            len(interrupted),
            len(waiting),
        )
    return {"interrupted": len(interrupted), "requeued": len(waiting)}


def queue_position(model: PredictionModel, ahead_counts: dict[int, int]) -> int | None:
    """佇列裡前面還有幾筆。training 是 0（就是它在跑），已完成的是 None。"""
    if model.status == "training":
        return 0
    if model.status != "queued":
        return None
    return ahead_counts.get(model.id, 0)


def count_ahead(db: Session, model_ids: list[int]) -> dict[int, int]:
    """一次算好每筆前面卡了幾個，避免列表頁對每一列各查一次。"""
    pending = [
        row_id
        for (row_id,) in db.query(PredictionModel.id)
        .filter(PredictionModel.status.in_(("queued", "training")))
        .order_by(PredictionModel.id.asc())
        .all()
    ]
    order = {row_id: i for i, row_id in enumerate(pending)}
    return {mid: order[mid] for mid in model_ids if mid in order}


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
