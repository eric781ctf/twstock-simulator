import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import (
    account,
    admin,
    auth,
    feature_flags,
    leaderboard,
    market_data,
    market_session,
    models,
    orders,
    positions,
    public_models,
    stocks,
    strategies,
    trades,
    watchlist,
)
from app.services.admin import ensure_admin_user
from app.services.app_config import ensure_app_config
from app.services.equity import snapshot_all_accounts_equity
from app.services.feature_flags import SCHEDULER_DAILY_BAR_BACKFILL, ensure_feature_flags, is_enabled
from app.services.migrations import run_lightweight_migrations
from app.services.ml.training_runner import shutdown_executor
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.stock_sync import backfill_twse_to_target, backfill_valuation_history, sync_stocks, sync_valuations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _backfill_valuation_history_task() -> None:
    """~36 次歷史快照回補要打不少外部 API，放到背景執行，不要卡住應用程式啟動。"""
    db = SessionLocal()
    try:
        await backfill_valuation_history(db)
    except Exception:
        logger.exception("backfill_valuation_history 背景任務發生錯誤")
    finally:
        db.close()


async def _backfill_daily_bars_task() -> None:
    """日K回補走「逐日抓全市場」，一個交易日一次請求就能拿到所有上市股票，
    補半年也只要百來次請求。仍然放到背景執行，不要卡住應用程式啟動；已經補過
    的日期會自己跳過，所以跟每日排程重複觸發也不會重複做工。"""
    db = SessionLocal()
    try:
        if is_enabled(db, SCHEDULER_DAILY_BAR_BACKFILL):
            await backfill_twse_to_target(db)
        else:
            logger.info("日K回補：功能已被管理員關閉，略過")
    except Exception:
        logger.exception("日K回補背景任務發生錯誤")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_lightweight_migrations(engine)

    db = SessionLocal()
    try:
        ensure_app_config(db)
        ensure_admin_user(db)
        ensure_feature_flags(db)
        count = await sync_stocks(db)
        if count == 0:
            logger.warning("啟動時股票清單同步失敗或無資料，將於背景排程重試")
        await sync_valuations(db)
        snapshot_all_accounts_equity(db)
    finally:
        db.close()

    backfill_task = asyncio.create_task(_backfill_valuation_history_task())
    daily_bars_backfill_task = asyncio.create_task(_backfill_daily_bars_task())
    start_scheduler()
    yield
    backfill_task.cancel()
    daily_bars_backfill_task.cancel()
    stop_scheduler()
    shutdown_executor()


app = FastAPI(title="TWStock 零股模擬交易", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(account.router)
app.include_router(positions.router)
app.include_router(orders.router)
app.include_router(trades.router)
app.include_router(market_data.router)
app.include_router(watchlist.router)
app.include_router(leaderboard.router)
app.include_router(market_session.router)
app.include_router(models.router)
app.include_router(public_models.router)
app.include_router(strategies.router)
app.include_router(admin.router)
app.include_router(feature_flags.router)


@app.get("/health")
def health():
    return {"status": "ok"}
