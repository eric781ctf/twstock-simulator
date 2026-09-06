import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.equity import snapshot_all_accounts_equity
from app.services.feature_flags import (
    SCHEDULER_DAILY_BAR_BACKFILL,
    SCHEDULER_DAILY_STOCK_SYNC,
    SCHEDULER_EQUITY_SNAPSHOT,
    SCHEDULER_MATCHING_POLL,
    SCHEDULER_MODEL_SCORING,
    SCHEDULER_STRATEGY_POLL,
    is_enabled,
)
from app.services.matching import (
    TAIPEI_TZ,
    expire_stale_orders,
    is_trading_hours,
    prune_old_price_points,
    run_matching_cycle,
)
from app.services.ml.inference import run_daily_scoring
from app.services.stock_sync import backfill_all_twse_daily_bars, sync_stocks, sync_valuations
from app.services.strategy_engine import run_strategy_cycle

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=TAIPEI_TZ)


async def _poll_job() -> None:
    db = SessionLocal()
    try:
        if not is_enabled(db, SCHEDULER_MATCHING_POLL):
            return
        expire_stale_orders(db)
        if is_trading_hours():
            await run_matching_cycle(db)
    except Exception:
        logger.exception("撮合輪詢發生錯誤")
    finally:
        db.close()


async def _strategy_poll_job() -> None:
    db = SessionLocal()
    try:
        if not is_enabled(db, SCHEDULER_STRATEGY_POLL):
            return
        await run_strategy_cycle(db)
    except Exception:
        logger.exception("策略輪詢發生錯誤")
    finally:
        db.close()


async def _daily_stock_sync_job() -> None:
    db = SessionLocal()
    try:
        if not is_enabled(db, SCHEDULER_DAILY_STOCK_SYNC):
            return
        prune_old_price_points(db)
        await sync_stocks(db)
    except Exception:
        logger.exception("每日股票清單同步發生錯誤")
    finally:
        db.close()


async def _daily_bar_backfill_job() -> None:
    db = SessionLocal()
    try:
        if not is_enabled(db, SCHEDULER_DAILY_BAR_BACKFILL):
            return
        await backfill_all_twse_daily_bars(db)
    except Exception:
        logger.exception("每日日K回補發生錯誤")
    finally:
        db.close()


async def _equity_snapshot_job() -> None:
    db = SessionLocal()
    try:
        if not is_enabled(db, SCHEDULER_EQUITY_SNAPSHOT):
            return
        snapshot_all_accounts_equity(db)
    except Exception:
        logger.exception("每日績效快照發生錯誤")
    finally:
        db.close()


async def _model_scoring_job() -> None:
    """交易日收盤後的模型選股。先同步一次股票清單，把「今天」的收盤價寫進
    daily_bars（TWSE 的 STOCK_DAY_ALL 大約下午 2 點半後就會更新當天資料），
    再讓每個啟用中的模型各自算分數、決定買賣。

    週末/假日不會有新的日K，run_daily_scoring 找不到當天的特徵列就會自己跳過，
    所以這裡不另外判斷是不是交易日。"""
    db = SessionLocal()
    try:
        if not is_enabled(db, SCHEDULER_MODEL_SCORING):
            return
        await sync_stocks(db)
        run_daily_scoring(db)
    except Exception:
        logger.exception("每日模型選股發生錯誤")
    finally:
        db.close()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.add_job(_poll_job, "interval", seconds=settings.poll_interval_seconds, id="matching_poll")
        scheduler.add_job(_strategy_poll_job, "interval", seconds=60, id="strategy_poll")
        scheduler.add_job(_daily_stock_sync_job, "cron", hour=8, minute=30, id="daily_stock_sync")
        scheduler.add_job(_daily_bar_backfill_job, "cron", hour=7, minute=0, id="daily_bar_backfill")
        # 排在每日股票同步（8:30）之後，確保當天最新一筆 daily_bars 收盤價
        # 已經寫進資料庫，快照的市值才不會用到前一天的舊資料。
        scheduler.add_job(_equity_snapshot_job, "cron", hour=8, minute=40, id="equity_snapshot")
        # 收盤（13:30）後，等 TWSE 官方把當天全市場收盤資料放上來再跑
        scheduler.add_job(_model_scoring_job, "cron", hour=15, minute=0, id="model_scoring")
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
