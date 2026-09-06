"""每日收盤後的選股與出場：對每個「訓練完成且未封存」的模型版本各跑一次。

不做盤中即時交易，也沒有當沖——固定在交易日收盤後跑一次，用當天的收盤價
開倉/平倉。資料來源是本地 daily_bars（由每日同步寫入），跟訓練時的特徵完全
同源，避免「訓練用日K、上線用即時報價」造成的分布落差。

每個模型跑完都會在 model_scoring_runs 留下耗時與成功/失敗紀錄。
"""

import logging
import time
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import DailyBar, ModelHolding, ModelScoringRun, PredictionModel
from app.services.ml import artifacts
from app.services.ml.exit_rules import net_return_percent
from app.services.ml.features import WARMUP_BARS, build_feature_rows
from app.services.ml.selection import OpenPosition, run_daily_cycle

logger = logging.getLogger(__name__)

WARMUP_CALENDAR_DAYS = WARMUP_BARS * 2


def get_active_models(db: Session) -> list[PredictionModel]:
    return (
        db.query(PredictionModel)
        .filter(
            PredictionModel.status == "completed",
            PredictionModel.is_archived.is_(False),
            PredictionModel.model_artifact_path.isnot(None),
        )
        .order_by(PredictionModel.id.asc())
        .all()
    )


def latest_bar_date(db: Session) -> date | None:
    return db.query(DailyBar.trade_date).order_by(DailyBar.trade_date.desc()).limit(1).scalar()


def _score_one_model(
    db: Session,
    model: PredictionModel,
    today: date,
    rows_today: list[dict],
    bars_by_code: dict[str, list[DailyBar]],
) -> int:
    """跑單一模型的當日循環，回傳這次的異動筆數（出場 + 進場）。"""
    bundle = artifacts.load_bundle(model.model_artifact_path)

    holdings = (
        db.query(ModelHolding)
        .filter(ModelHolding.model_id == model.id, ModelHolding.source == "live", ModelHolding.status == "open")
        .all()
    )
    open_positions = [
        OpenPosition(
            stock_code=h.stock_code,
            entry_date=h.entry_date,
            entry_price=h.entry_price,
            ref=h,
        )
        for h in holdings
    ]

    bar_index = {code: {bar.trade_date: i for i, bar in enumerate(bars)} for code, bars in bars_by_code.items()}
    bars_until_today = {}
    for row in rows_today:
        code = row["stock_code"]
        index = bar_index.get(code, {}).get(today)
        if index is not None:
            bars_until_today[code] = bars_by_code[code][: index + 1]

    exits, entries = run_daily_cycle(model, bundle, today, rows_today, bars_until_today, open_positions)

    for action in exits:
        holding: ModelHolding = action.position.ref
        holding.exit_date = today
        holding.exit_price = action.exit_price
        holding.status = "closed"
        holding.return_percent = net_return_percent(holding.entry_price, action.exit_price)
        holding.exit_reason = action.reason

    for entry in entries:
        db.add(
            ModelHolding(
                model_id=model.id,
                stock_code=entry.stock_code,
                source="live",
                entry_date=today,
                entry_price=entry.entry_price,
                status="open",
            )
        )

    db.commit()
    logger.info("模型 %d(%s v%d)：出場 %d 筆、進場 %d 筆", model.id, model.model_family, model.version, len(exits), len(entries))
    return len(exits) + len(entries)


def run_daily_scoring(db: Session, today: date | None = None) -> int:
    """對所有啟用中的模型跑當日選股。回傳實際跑完的模型數。

    today 預設用「本地日K最新的交易日」而不是系統日期——這樣週末或資料還沒
    發布時不會憑空產生一個沒有價格的交易日，重跑也會自然對齊同一天。
    """
    models = get_active_models(db)
    if not models:
        return 0

    today = today or latest_bar_date(db)
    if today is None:
        logger.warning("run_daily_scoring: 本地沒有任何日K資料，略過")
        return 0

    fetch_start = today - timedelta(days=WARMUP_CALENDAR_DAYS)
    rows, bars_by_code = build_feature_rows(db, fetch_start, today, today)
    rows_today = [row for row in rows if row["as_of_date"] == today]
    if not rows_today:
        logger.warning("run_daily_scoring: %s 沒有可用的特徵列（可能不是交易日或資料未同步），略過", today)
        return 0

    done = 0
    for model in models:
        existing = (
            db.query(ModelScoringRun)
            .filter(ModelScoringRun.model_id == model.id, ModelScoringRun.run_date == today)
            .first()
        )
        if existing is not None and existing.status == "success":
            continue  # 同一天同一個模型只跑一次，排程重觸發不會重複開倉

        started = time.perf_counter()
        try:
            _score_one_model(db, model, today, rows_today, bars_by_code)
            status, error = "success", None
        except Exception as e:
            logger.exception("模型 %d 當日選股失敗", model.id)
            db.rollback()
            status, error = "failed", str(e)[:500]

        duration = time.perf_counter() - started
        if existing is not None:
            existing.duration_seconds = duration
            existing.status = status
            existing.error_message = error
        else:
            db.add(
                ModelScoringRun(
                    model_id=model.id,
                    run_date=today,
                    duration_seconds=duration,
                    status=status,
                    error_message=error,
                )
            )
        db.commit()
        if status == "success":
            done += 1

    logger.info("run_daily_scoring: %s 完成 %d/%d 個模型", today, done, len(models))
    return done
