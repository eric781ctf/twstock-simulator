from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import Market, OrderStatus, Side


class StockOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    market: Market


class QuoteOut(BaseModel):
    code: str
    name: str
    price: float | None
    prev_close: float | None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    is_stale: bool


class FundamentalsOut(BaseModel):
    stock_code: str
    pe_ratio: float | None
    dividend_yield: float | None
    pb_ratio: float | None
    updated_at: datetime | None


class AccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    cash_balance: float
    frozen_cash: float
    available_cash: float


class PositionOut(BaseModel):
    stock_code: str
    stock_name: str
    quantity: int
    frozen_quantity: int
    avg_cost: float
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None


class OrderCreate(BaseModel):
    stock_code: str
    side: Side
    price: float = Field(gt=0)
    quantity: int = Field(gt=0, lt=1000)


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stock_code: str
    side: Side
    price: float
    quantity: int
    status: OrderStatus
    created_at: datetime
    filled_at: datetime | None
    filled_price: float | None


class WatchlistItemOut(BaseModel):
    stock_code: str
    stock_name: str
    market: Market
    created_at: datetime
    current_price: float | None = None


class WatchlistCreate(BaseModel):
    stock_code: str


class AdminAccountOut(BaseModel):
    user_id: int
    username: str
    nickname: str
    is_admin: bool
    cash_balance: float | None
    frozen_cash: float | None
    frozen_until: datetime | None
    created_at: datetime


class AdminAmountIn(BaseModel):
    amount: float = Field(gt=0)


class DefaultInitialCashOut(BaseModel):
    amount: float


class MarketSessionOut(BaseModel):
    status: Literal["trading", "after_hours", "closed"]
    trading_start: str
    trading_end: str
    after_hours_end: str


class LeaderboardEntryOut(BaseModel):
    nickname: str
    total_assets: float
    cash_balance: float
    market_value: float


class TradeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    stock_code: str
    side: Side
    price: float
    quantity: int
    amount: float
    fee: float
    tax: float
    executed_at: datetime
