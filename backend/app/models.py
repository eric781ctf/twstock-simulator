import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Market(str, enum.Enum):
    TWSE = "TWSE"
    TPEX = "TPEX"


class Side(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(100), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frozen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppConfig(Base):
    """全站設定，目前只有一列（id 固定為 1）。放預設啟動資金這種「改了只影響
    以後」的設定，跟個別帳戶的即時資料分開，也讓管理員改的值能重開機後還在，
    不像 Settings 那樣只在啟動當下讀一次 .env。"""

    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    default_initial_cash: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)


class FeatureFlag(Base):
    """功能模組開關，讓管理員不用重新部署就能暫停某個功能。key 是固定的
    字串代碼（見 services/feature_flags.py 的 FLAG_KEYS），不是給使用者
    自訂的名稱。"""

    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(50), default="示範帳號")
    cash_balance: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    frozen_cash: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Stock(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[Market] = mapped_column(Enum(Market), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "stock_code", name="uq_position_account_stock"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    frozen_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)

    stock: Mapped["Stock"] = relationship()


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    side: Mapped[Side] = mapped_column(Enum(Side), nullable=False)
    order_type: Mapped[str] = mapped_column(String(10), nullable=False, default="limit")
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    stop_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), nullable=False, default=OrderStatus.PENDING)
    reserved_amount: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)

    stock: Mapped["Stock"] = relationship()


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    side: Mapped[Side] = mapped_column(Enum(Side), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    fee: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    tax: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    realized_pnl: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stock: Mapped["Stock"] = relationship()


class DailyBar(Base):
    """個股日 K 線（開高低收量）。TWSE 股票會從官方歷史 API 一次回補約 3 個月，
    TPEx 股票沒有公開的多日歷史端點，只能從系統啟動後每日同步時逐日累積。"""

    __tablename__ = "daily_bars"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_daily_bar_stock_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PricePoint(Base):
    """盤中即時價格快照，用來畫當日分時走勢線。由背景輪詢工作逐筆累積，
    僅保留「有人持有」或「在某人自選股清單」的股票。每日同步時會清掉前一日以前
    的資料（當日 OHLC 已經寫進 daily_bars，分時明細用不到），避免無限長大。"""

    __tablename__ = "price_points"
    __table_args__ = (Index("ix_price_points_stock_ts", "stock_code", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    price: Mapped[float] = mapped_column(Float, nullable=False)


class StockValuationHistory(Base):
    """個股本益比、殖利率、股價淨值比的歷史快照。TWSE 股票會用官方的「依日期查詢」
    端點一次回補約 3 年的月度快照；TPEx 沒有這種依日期查詢的公開端點，只能從系統
    啟動後每日同步時逐日累積（跟 daily_bars 的 TPEx 處理方式一樣）。"""

    __tablename__ = "stock_valuation_history"
    __table_args__ = (UniqueConstraint("stock_code", "as_of_date", name="uq_valuation_history_stock_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    dividend_yield: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)


class Strategy(Base):
    """自動化交易策略。買進條件掃描全市場（凡是本地有足夠日K資料的股票都會被檢查），
    依 rank_by 排序後只對前 top_n 檔下單；賣出條件套用在該帳戶「目前所有持股」上，
    不限定是不是這組策略買的。同一帳戶同時只會有一組 is_active=True（由
    routers/strategies.py 的 activate 端點負責切換，非資料庫層級約束）。"""

    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    buy_conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sell_conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rank_by: Mapped[str] = mapped_column(String(20), nullable=False, default="change_percent")
    rank_direction: Mapped[str] = mapped_column(String(4), nullable=False, default="desc")
    top_n: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StrategyTrade(Base):
    """策略自動下單的執行紀錄，同時也是「同一天同一檔股票同方向不重複下單」的
    去重依據——每分鐘都會重新檢查條件，沒有這個表會一直重複買/賣同一檔。"""

    __tablename__ = "strategy_trades"
    __table_args__ = (
        UniqueConstraint("strategy_id", "stock_code", "side", "trade_date", name="uq_strategy_trade_daily"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("strategies.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    side: Mapped[Side] = mapped_column(Enum(Side), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stock: Mapped["Stock"] = relationship()


class EquitySnapshot(Base):
    """帳戶每日績效快照（現金、部位市值、總資產），給「績效走勢圖」用。刻意
    只在每日排程（見 services/equity.py）用 daily_bars 的收盤價計算，不即時
    打報價 API——這樣使用者的績效歷史用不到額外的 API 額度，跟市價單共用
    quote_cache 的節流精神一致。同一帳戶同一天只會有一筆（見 unique
    constraint），排程重跑會直接覆蓋更新，不會重複累積。"""

    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "snapshot_date", name="uq_equity_snapshot_account_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    cash_balance: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    market_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    total_assets: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)


class WatchlistItem(Base):
    """使用者自選股清單，每個帳戶最多 20 檔。清單內的股票會被排入每日分時資料
    的追蹤範圍（見 matching.run_matching_cycle），並顯示在該使用者首頁。"""

    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("account_id", "stock_code", name="uq_watchlist_account_stock"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    stock: Mapped["Stock"] = relationship()
