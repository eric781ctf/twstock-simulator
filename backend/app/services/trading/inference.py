"""每日收盤後的選股與出場：對每個「訓練完成且未封存」的模型版本各跑一次。

不做盤中即時交易，也沒有當沖——固定在交易日收盤後跑一次，用當天的收盤價
開倉/平倉。資料來源是本地 daily_bars（由每日同步寫入），跟訓練時的特徵完全
同源，避免「訓練用日K、上線用即時報價」造成的分布落差。

每個模型跑完都會在 model_scoring_runs 留下耗時與成功/失敗紀錄。
"""

import logging
import time
from datetime import date, timedelta

import numpy as np
from sqlalchemy.orm import Session

from app.models import DailyBar, Market, ModelHolding, ModelScoringRun, PredictionModel, Stock
from app.services.modeling import artifacts
from app.services.trading.exit_rules import net_return_percent
from app.services.ingest.industry_sync import load_industry_map
from app.services.features.transforms import SCALING_RANK, industry_neutralize, rank_normalize
from app.services.features.builder import CROSS_SECTION_SKIP_KEYS, WARMUP_BARS, build_feature_rows
from app.services.features.universe import is_ordinary_stock
from app.services.trading.selection import OpenPosition, run_daily_cycle
from app.services.features.sequences import DEFAULT_SEQUENCE_LENGTH, index_feature_rows
from app.services.modeling.train import SEQUENCE_MODEL_TYPES

logger = logging.getLogger(__name__)

WARMUP_CALENDAR_DAYS = WARMUP_BARS * 2

# 交易日換算成日曆天的粗略倍數（一週 5 個交易日 / 7 天），再多留一點緩衝
TRADING_DAY_TO_CALENDAR = 1.6


def _max_sequence_length(models: list[PredictionModel]) -> int:
    """這批模型裡最長的視窗長度；沒有序列模型就回 0。"""
    lengths = [
        int((m.network_config or {}).get("sequence_length") or DEFAULT_SEQUENCE_LENGTH)
        for m in models
        if m.model_type in SEQUENCE_MODEL_TYPES
    ]
    return max(lengths) if lengths else 0


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
    """本地日K最新的**上市**交易日。

    一定要限定 TWSE：這個系統只做上市股票，但 daily_bars 裡還有上櫃資料，而兩邊
    的同步時間不一定同步。上櫃先進來、上市還沒進來時，不限定市場會回傳一個
    「對這個系統來說根本沒有資料」的日期，當日選股就會整批被略過。
    """
    return (
        db.query(DailyBar.trade_date)
        .join(Stock, Stock.code == DailyBar.stock_code)
        .filter(Stock.market == Market.TWSE)
        .order_by(DailyBar.trade_date.desc())
        .limit(1)
        .scalar()
    )


def _held_codes_outside_universe(db: Session, models: list[PredictionModel]) -> set[str]:
    """還開著、但代號不在普通股母體裡的正式持有。

    母體收窄之前，模型挑過槓桿 ETF、ETN、TDR。那些部位要照各自的出場規則
    走完，所以得繼續拿到它們的價格——否則 run_daily_cycle 會因為「今天沒有
    K 棒」而永遠續抱，佔著名額不放。出場之後這個集合自然變空。
    """
    rows = (
        db.query(ModelHolding.stock_code)
        .filter(
            ModelHolding.model_id.in_([m.id for m in models]),
            ModelHolding.source == "live",
            ModelHolding.status == "open",
        )
        .distinct()
        .all()
    )
    return {code for (code,) in rows if not is_ordinary_stock(code)}


def _score_one_model(
    db: Session,
    model: PredictionModel,
    today: date,
    rows_today: list[dict],
    signal_rows: list[dict],
    all_rows: list[dict],
    bars_by_code: dict[str, list[DailyBar]],
) -> int:
    """跑單一模型的當日循環，回傳這次的異動筆數（出場 + 進場）。

    signal_rows 是前一個交易日的特徵列，進場排名用它算；rows_today 只提供
    今天的成交價與漲跌停狀態。all_rows 含今天之前那段歷史，只有序列模型會用到。
    """
    bundle = artifacts.load_bundle(model.model_artifact_path)

    # 橫斷面轉換要套在「訊號那一天的全市場」上，跟訓練時的基準一致。若只對
    # 候選股（已扣掉手上持有的）排名，同一檔的名次會因為手上有幾檔而漂移
    if bundle.feature_scaling == SCALING_RANK:
        signal_rows = rank_normalize(signal_rows, bundle.feature_keys, skip=set(CROSS_SECTION_SKIP_KEYS))

    if bundle.industry_neutral:
        signal_rows = industry_neutralize(
            signal_rows, bundle.feature_keys, load_industry_map(db), skip=set(CROSS_SECTION_SKIP_KEYS)
        )

    if bundle.sequence_length:
        # 每個模型的特徵欄位與順序可能不同，序列矩陣的欄位順序必須跟該模型
        # 訓練當下一致，所以索引要用這個 bundle 自己的 feature_keys 重建，
        # 不能讓多個模型共用同一份。
        index_feature_rows(all_rows, bundle.feature_keys)

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
    for code in rows_today.stock_codes():
        index = bar_index.get(code, {}).get(today)
        if index is not None:
            bars_until_today[code] = bars_by_code[code][: index + 1]

    exits, entries = run_daily_cycle(
        model, bundle, today, rows_today, signal_rows, bars_until_today, open_positions
    )

    for action in exits:
        holding: ModelHolding = action.position.ref
        holding.exit_date = today
        # float() 不是多餘的：價格是從特徵矩陣取出來的 np.float64，
        # psycopg2 不認得 numpy 純量
        holding.exit_price = float(action.exit_price)
        holding.status = "closed"
        holding.return_percent = float(net_return_percent(holding.entry_price, action.exit_price))
        holding.exit_reason = action.reason

    for entry in entries:
        db.add(
            ModelHolding(
                model_id=model.id,
                stock_code=str(entry.stock_code),
                source="live",
                entry_date=today,
                entry_price=float(entry.entry_price),
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

    **next_open 模式的模型也是在 15:00 這一班跑，這是刻意的。** 那種模型的
    決策時點是當天 09:00 之前（訊號來自昨天的特徵加昨晚的夜盤），成交價是
    當天的開盤價。09:00 之前開盤價還不存在，所以真要在盤前跑，也得等開盤
    之後才填得了成交價。收盤後一次跑完，決策內容跟 08:50 跑出來的完全一樣
    （用到的資料都在 09:00 前就已知），差別只在部位晚幾個小時才出現在畫面上。
    """
    models = get_active_models(db)
    if not models:
        return 0

    today = today or latest_bar_date(db)
    if today is None:
        logger.warning("run_daily_scoring: 本地沒有任何日K資料，略過")
        return 0

    # 序列模型要看今天之前連續 T 天的特徵，所以特徵列不能只產出今天這一天。
    # 取所有啟用中模型裡最長的那個視窗，一次撈足，全部模型共用同一份。
    max_sequence = _max_sequence_length(models)
    # 至少要多涵蓋一個交易日：進場訊號取的是前一天。抓 10 個日曆天是為了
    # 跨過週末與連假，不然遇到長假就找不到前一個交易日
    feature_start = today - timedelta(days=10)
    if max_sequence:
        feature_start = today - timedelta(days=int(max_sequence * TRADING_DAY_TO_CALENDAR) + 7)

    fetch_start = feature_start - timedelta(days=WARMUP_CALENDAR_DAYS)
    legacy_codes = _held_codes_outside_universe(db, models)
    if legacy_codes:
        logger.info("run_daily_scoring: 母體外仍有未平倉持有，照常出場但不再進場：%s", sorted(legacy_codes))
    rows, bars_by_code = build_feature_rows(db, fetch_start, today, feature_start, legacy_codes)
    rows_today = rows.on_date(today)
    if not rows_today:
        logger.warning("run_daily_scoring: %s 沒有可用的特徵列（可能不是交易日或資料未同步），略過", today)
        return 0

    previous_days = rows.before(today).unique_dates()
    if not previous_days:
        logger.warning("run_daily_scoring: 找不到 %s 的前一個交易日，無法產生進場訊號，略過", today)
        return 0
    signal_day = previous_days[-1]
    signal_rows = rows.on_date(signal_day)
    if legacy_codes:
        # 候選只能來自母體；排名化也要在濾掉之後做，名次才跟訓練時的橫斷面一致
        signal_rows = signal_rows.mask(
            np.array([is_ordinary_stock(c) for c in signal_rows.stock_codes()], dtype=bool)
        )
    logger.info("run_daily_scoring: %s 成交，進場訊號取自 %s", today, signal_day)

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
            _score_one_model(db, model, today, rows_today, signal_rows, rows, bars_by_code)
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
