import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.routers import account, auth, market_data, orders, positions, stocks, trades, watchlist
from app.services.scheduler import start_scheduler, stop_scheduler
from app.services.stock_sync import sync_stocks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        count = await sync_stocks(db)
        if count == 0:
            logger.warning("啟動時股票清單同步失敗或無資料，將於背景排程重試")
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="TWStock 零股模擬交易", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
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


@app.get("/health")
def health():
    return {"status": "ok"}
