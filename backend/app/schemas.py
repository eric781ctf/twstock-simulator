from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    order_type: Literal["limit", "market", "stop"] = "limit"
    price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    quantity: int = Field(gt=0, lt=1000)

    @model_validator(mode="after")
    def _check_price_fields(self):
        if self.order_type == "limit" and self.price is None:
            raise ValueError("限價單需要輸入價格")
        if self.order_type == "stop" and self.stop_price is None:
            raise ValueError("停損單需要輸入觸發價")
        return self


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stock_code: str
    side: Side
    order_type: str
    price: float
    stop_price: float | None
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


class DailyBarBucketOut(BaseModel):
    label: str
    count: int


class DailyBarMarketStatsOut(BaseModel):
    total_stocks: int
    sufficient: int
    insufficient: int
    buckets: list[DailyBarBucketOut]


class DailyBarStatsOut(BaseModel):
    twse: DailyBarMarketStatsOut
    tpex: DailyBarMarketStatsOut


class FeatureFlagOut(BaseModel):
    key: str
    label: str
    enabled: bool


class FeatureFlagUpdateIn(BaseModel):
    enabled: bool


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


class StrategyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    quantity: int = Field(gt=0, lt=1000)
    buy_conditions: list[dict] = Field(default_factory=list)
    sell_conditions: list[dict] = Field(default_factory=list)
    rank_by: Literal["change_percent", "k_value", "d_value", "volume"] = "change_percent"
    rank_direction: Literal["asc", "desc"] = "desc"
    top_n: int = Field(gt=0, le=50)


class StrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool
    quantity: int
    buy_conditions: list[dict]
    sell_conditions: list[dict]
    rank_by: str
    rank_direction: str
    top_n: int
    created_at: datetime


class StrategyTradeOut(BaseModel):
    id: int
    stock_code: str
    stock_name: str
    side: Side
    trade_date: str
    price: float | None
    quantity: int | None
    status: OrderStatus | None


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
    realized_pnl: float | None
    executed_at: datetime


class RealizedPnlSummaryOut(BaseModel):
    total_realized_pnl: float
    win_count: int
    loss_count: int
    win_rate: float | None


class EquitySnapshotOut(BaseModel):
    snapshot_date: str
    cash_balance: float
    market_value: float
    total_assets: float


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    initial_cash: float = Field(default=1_000_000, gt=0)


class EquityCurvePointOut(BaseModel):
    date: str
    total_assets: float


class BacktestResultOut(BaseModel):
    start_date: str
    end_date: str
    initial_cash: float
    final_assets: float
    total_return_percent: float
    max_drawdown_percent: float
    trade_count: int
    win_count: int
    loss_count: int
    win_rate: float | None
    equity_curve: list[EquityCurvePointOut]
    warning: str | None = None
