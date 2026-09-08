import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
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
    target_backfill_months: Mapped[int] = mapped_column(Integer, nullable=False, default=3)


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
    # 全市場單日成交股數會超過 int4 上限（21 億），高人氣 ETF 一天就能撞到
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


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


class PredictionModel(Base):
    """一次訓練 = 一筆不可變的模型版本。重新訓練不會覆蓋舊的，而是在同一個
    model_family 底下長出新的 version，這樣「舊版本當時的績效」才不會因為重訓
    就被洗掉。status 本身就是訓練工作的進度（不另外開一張 job 表），admin 頁面
    直接輪詢這個欄位就知道跑到哪了。

    封存（is_archived）只是讓它不再參與每日選股，歷史持有跟績效都還看得到。"""

    __tablename__ = "prediction_models"
    __table_args__ = (UniqueConstraint("model_family", "version", name="uq_prediction_model_family_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_family: Mapped[str] = mapped_column(String(50), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_type: Mapped[str] = mapped_column(String(30), nullable=False)
    feature_config: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 預測目標：未來 n_days 天的報酬率（迴歸），以及是否超過 threshold_percent（分類）
    n_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    threshold_percent: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)

    # 選股分數一律用橫斷面標準化加權（見 services/ml/train.py 的 SCORE_FORMULA_INFO）
    score_formula: Mapped[str] = mapped_column(String(20), nullable=False, default="zscore_weighted")
    score_weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 神經網路類型才會用到：層數與每層神經元數、啟用函數、dropout、epochs 等
    network_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 出場規則（四層，依序判斷，見 services/ml/exit_rules.py）
    min_hold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hold_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_loss_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    sell_conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # 依時間切分的六個界線，由 admin 在訓練表單自己指定
    train_start: Mapped[date] = mapped_column(Date, nullable=False)
    train_end: Mapped[date] = mapped_column(Date, nullable=False)
    validation_start: Mapped[date] = mapped_column(Date, nullable=False)
    validation_end: Mapped[date] = mapped_column(Date, nullable=False)
    test_start: Mapped[date] = mapped_column(Date, nullable=False)
    test_end: Mapped[date] = mapped_column(Date, nullable=False)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    training_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_artifact_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelScoringRun(Base):
    """每個模型每一天跑選股/出場判斷的執行紀錄，主要是為了記錄耗時，順便當成
    每日排程的稽核軌跡（哪天跑了、成功還失敗）。"""

    __tablename__ = "model_scoring_runs"
    __table_args__ = (UniqueConstraint("model_id", "run_date", name="uq_model_scoring_run_daily"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("prediction_models.id"), nullable=False)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelPrediction(Base):
    """回測（測試集）逐筆的「預測 vs 實際」，餵給迴歸散佈圖跟分類校準曲線。
    只存測試集——訓練集/驗證集的預測沒有評估意義（模型看過答案）。"""

    __tablename__ = "model_predictions"
    __table_args__ = (Index("ix_model_predictions_model_date", "model_id", "as_of_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("prediction_models.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_return_percent: Mapped[float] = mapped_column(Float, nullable=False)
    actual_return_percent: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_probability: Mapped[float] = mapped_column(Float, nullable=False)
    actual_label: Mapped[bool] = mapped_column(Boolean, nullable=False)


class ModelHolding(Base):
    """模型的持有紀錄，回測模擬（source=backtest）跟正式上線後（source=live）
    共用同一張表——兩者形狀完全一樣，差別只在是哪一段時間、由誰觸發的。

    刻意不記錄股數或金額：這個系統只追蹤「損益率」，return_percent 已經扣掉
    買賣手續費與賣出證交稅（見 services/ml/exit_rules.py 的 net_return_percent）。"""

    __tablename__ = "model_holdings"
    __table_args__ = (Index("ix_model_holdings_model_source", "model_id", "source", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("prediction_models.id"), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="live")
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)


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
