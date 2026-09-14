import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.platform.feature_flags import (
    SCHEDULER_DAILY_BAR_BACKFILL,
    SCHEDULER_DAILY_STOCK_SYNC,
    SCHEDULER_MODEL_SCORING,
    is_enabled,
)
from app.services.trading.inference import run_daily_scoring
from app.services.platform.clock import TAIPEI_TZ
from app.services.ingest.stock_sync import backfill_twse_to_target, sync_stocks, sync_valuations

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=TAIPEI_TZ)




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
        await backfill_twse_to_target(db)
    except Exception:
        logger.exception("每日日K回補發生錯誤")
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
        scheduler.add_job(_daily_stock_sync_job, "cron", hour=8, minute=30, id="daily_stock_sync")
        scheduler.add_job(_daily_bar_backfill_job, "cron", hour=7, minute=0, id="daily_bar_backfill")
        # 收盤（13:30）後，等 TWSE 官方把當天全市場收盤資料放上來再跑
        scheduler.add_job(_model_scoring_job, "cron", hour=15, minute=0, id="model_scoring")
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
