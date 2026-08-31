import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.database import SessionLocal
from app.services.matching import (
    TAIPEI_TZ,
    expire_stale_orders,
    is_trading_hours,
    prune_old_price_points,
    run_matching_cycle,
)
from app.services.stock_sync import sync_stocks, sync_valuations
from app.services.strategy_engine import run_strategy_cycle

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone=TAIPEI_TZ)


async def _poll_job() -> None:
    db = SessionLocal()
    try:
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
        await run_strategy_cycle(db)
    except Exception:
        logger.exception("策略輪詢發生錯誤")
    finally:
        db.close()


async def _daily_stock_sync_job() -> None:
    db = SessionLocal()
    try:
        prune_old_price_points(db)
        await sync_stocks(db)
    except Exception:
        logger.exception("每日股票清單同步發生錯誤")
    finally:
        db.close()


def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.add_job(_poll_job, "interval", seconds=settings.poll_interval_seconds, id="matching_poll")
        scheduler.add_job(_strategy_poll_job, "interval", seconds=60, id="strategy_poll")
        scheduler.add_job(_daily_stock_sync_job, "cron", hour=8, minute=30, id="daily_stock_sync")
        scheduler.start()


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
