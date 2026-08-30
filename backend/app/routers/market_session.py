from fastapi import APIRouter

from app.config import settings
from app.schemas import MarketSessionOut
from app.services.matching import is_after_hours_window, is_trading_hours

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/session", response_model=MarketSessionOut)
def get_market_session():
    if is_trading_hours():
        status = "trading"
    elif is_after_hours_window():
        status = "after_hours"
    else:
        status = "closed"
    return MarketSessionOut(status=status, trading_start=settings.trading_start, trading_end=settings.trading_end)
