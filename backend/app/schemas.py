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


class BackfillProgressOut(BaseModel):
    """回補任務當下的即時進度。phase 分成閒置/準備中/回補中/節流等待中/
    被限流中止/完成/失敗——特別要能分辨「我們主動節流」跟「被 TWSE 擋」。"""

    # 現在跑的是哪一種回補（日K／籌碼面）——兩者共用同一個狀態
    job: str
    job_label: str
    phase: str
    phase_label: str
    current_target: str | None
    processed: int
    total: int
    remaining_targets: int
    written_bars: int
    wait_seconds_remaining: int | None
    wait_reason: str | None
    message: str | None
    started_at: datetime | None
    finished_at: datetime | None


class BackfillStatusOut(BaseModel):
    earliest_date: date | None
    target_months: int
    progress: BackfillProgressOut


class ChipStatusOut(BaseModel):
    """籌碼面資料的覆蓋範圍與當下的回補進度。"""

    earliest_date: date | None
    latest_date: date | None
    total_rows: int
    progress: BackfillProgressOut


class BackfillTargetIn(BaseModel):
    target_months: int = Field(gt=0, le=120)


class FeatureOptionOut(BaseModel):
    key: str
    label: str


class ModelTypeOptionOut(BaseModel):
    key: str
    label: str
    # 有「層」這個概念、需要 GPU 的類型；前端據此決定要不要顯示網路結構設定
    is_neural: bool
    # 吃「連續 T 天的視窗」的類型（GRU/LSTM）；前端據此多顯示序列長度欄位
    is_sequence: bool = False
    # 樹模型；前端據此顯示樹的超參數設定
    is_tree: bool = False
    # 隨機森林沒有學習率，那一欄要停用
    has_learning_rate: bool = True


class NetworkLayerOut(BaseModel):
    """網路的一層，欄位刻意對齊 Keras model.summary() 的呈現方式。"""

    name: str
    type: str
    output_shape: str
    params: int


class LossCurvePointOut(BaseModel):
    epoch: int
    train_loss: float
    validation_loss: float


class NetworkInfoOut(BaseModel):
    layers: list[NetworkLayerOut]
    total_params: int
    loss_curve: list[LossCurvePointOut]
    device: str
    epochs: int
    hidden_sizes: list[int]
    activation: str
    dropout: float
    # 只有 GRU/LSTM 有：一個樣本往回看幾個交易日
    sequence_length: int | None = None
    kind: str | None = None
    # 早停：實際跑到第幾輪、哪一輪的驗證 loss 最低（存下來的就是那一輪的權重）
    configured_epochs: int | None = None
    best_epoch: int | None = None
    early_stopped: bool = False
    patience: int | None = None
    batch_size: int | None = None


class NetworkConfigIn(BaseModel):
    """神經網路的結構設定，只有 model_type 是神經網路類型時才會用到。"""

    hidden_sizes: list[int] = Field(default_factory=lambda: [64, 32], min_length=1, max_length=8)
    activation: Literal["relu", "tanh", "gelu"] = "relu"
    dropout: float = Field(default=0.2, ge=0, le=0.9)
    learning_rate: float = Field(default=0.001, gt=0, le=1)
    epochs: int = Field(default=60, ge=1, le=1000)
    # GRU/LSTM 專用；MLP 會忽略這個值
    sequence_length: int = Field(default=20, ge=5, le=120)
    # 早停耐心值。0 = 關閉，跑滿 epochs 並採用最後一輪的權重
    patience: int = Field(default=10, ge=0, le=200)
    # 一次送進網路幾筆。調小可以避開顯示記憶體不足，但訓練會變慢
    batch_size: int = Field(default=512, ge=8, le=16384)

    @model_validator(mode="after")
    def _check_sizes(self):
        if any(size < 1 or size > 1024 for size in self.hidden_sizes):
            raise ValueError("每層神經元數必須介於 1~1024")
        return self


class TreeConfigIn(BaseModel):
    """樹模型的超參數。名稱刻意取通用的，後端再翻譯成各套件自己的參數名。"""

    n_estimators: int = Field(default=300, ge=10, le=5000)
    max_depth: int = Field(default=6, ge=1, le=32)
    # 隨機森林沒有學習率（樹各自獨立長，不是一棵補一棵），送了會被忽略
    learning_rate: float = Field(default=0.05, gt=0, le=1)
    subsample: float = Field(default=0.8, gt=0, le=1)
    colsample: float = Field(default=0.8, gt=0, le=1)
    min_child_samples: int = Field(default=20, ge=1, le=10000)


class WalkForwardConfigIn(BaseModel):
    """滾動視窗的各段月數。整段期間由六個切分日期裡的 train_start 與 test_end 決定，
    這裡只描述「每一折長什麼樣、每次往前滾多久」。"""

    train_months: int = Field(default=6, ge=1, le=60)
    validation_months: int = Field(default=2, ge=1, le=24)
    test_months: int = Field(default=2, ge=1, le=24)
    step_months: int = Field(default=2, ge=1, le=24)


class FoldMetricsOut(BaseModel):
    """一折的切分日期與三段成績。"""

    fold: dict
    train: dict
    validation: dict
    test: dict


class WalkForwardStatOut(BaseModel):
    mean: float
    std: float
    min: float
    max: float
    positive_folds: int
    count: int


class WalkForwardSummaryOut(BaseModel):
    """折間統計。標準差才是重點——平均 +0.02 但標準差 0.06 的訊號站不住腳。"""

    fold_count: int
    test_rank_ic: WalkForwardStatOut | None = None
    test_auc: WalkForwardStatOut | None = None
    validation_rank_ic: WalkForwardStatOut | None = None


class ModelDeleteResultOut(BaseModel):
    """刪除結果連帶刪掉多少東西一起回報，讓 admin 看得到這次到底移除了什麼。"""

    model_config = ConfigDict(protected_namespaces=())

    deleted: bool
    model_id: int
    label: str
    deleted_predictions: int
    deleted_holdings: int
    deleted_scoring_runs: int
    removed_artifact: bool


class ModelCatalogOut(BaseModel):
    """模型教學頁的資料來源：這個系統「實際上」支援哪些模型、用什麼公式選股、
    每天持有幾檔、費率多少。全部取自後端實作，教學頁才不會跟實作走鐘。"""

    model_types: list["ModelTypeOptionOut"]
    score_formula: "ScoreFormulaInfoOut"
    features: list["FeatureOptionOut"]
    top_n: int
    commission_rate: float
    tax_rate: float


class ScoreFormulaInfoOut(BaseModel):
    """選股分數的公式與白話說明，給前端直接顯示——公式定義只有後端一份，
    前端不自己抄，改公式時不會有兩邊講不一樣的情況。"""

    key: str
    name: str
    formula: str
    definition: str
    summary: str
    reasons: list[str]
    limitation: str


class FeaturePresetOut(BaseModel):
    """現成的特徵組合。71 個勾選框沒辦法用，預設集才是實際的操作方式。"""

    key: str
    label: str
    description: str
    features: list[str]


class TrainDefaultsOut(BaseModel):
    """給訓練表單用的預設值與可選項目：建議的六個切分日期（依本地資料最新
    日期往回推）、可勾選的特徵、可選的模型類型。"""

    latest_data_date: date | None
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date
    default_features: list[str]
    feature_presets: list[FeaturePresetOut]
    features: list[FeatureOptionOut]
    model_types: list[ModelTypeOptionOut]
    score_formula: ScoreFormulaInfoOut


class ModelTrainRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_family: str = Field(min_length=1, max_length=50)
    model_type: Literal["xgboost", "lightgbm", "random_forest", "logistic_regression", "mlp", "gru", "lstm"]
    feature_config: list[str] = Field(min_length=1)
    n_days: int = Field(gt=0, le=60)
    threshold_percent: float
    label_mode: Literal["absolute", "excess"] = "excess"
    # 公式固定用橫斷面標準化，只有權重可調
    score_weights: dict | None = None
    network_config: NetworkConfigIn | None = None
    tree_config: TreeConfigIn | None = None
    validation_mode: Literal["single", "walk_forward"] = "single"
    feature_scaling: Literal["zscore", "cross_sectional_rank"] = "cross_sectional_rank"
    walk_forward_config: WalkForwardConfigIn | None = None

    min_hold_days: int | None = Field(default=None, ge=0, le=250)
    max_hold_days: int | None = Field(default=None, ge=1, le=250)
    stop_loss_percent: float | None = Field(default=None, gt=0, le=100)
    take_profit_percent: float | None = Field(default=None, gt=0, le=1000)
    sell_conditions: list[dict] = Field(default_factory=list)

    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    @model_validator(mode="after")
    def _check(self):
        if not (self.train_start < self.train_end < self.validation_start < self.validation_end < self.test_start < self.test_end):
            raise ValueError("日期必須依序遞增：訓練起 < 訓練迄 < 驗證起 < 驗證迄 < 測試起 < 測試迄")
        if self.min_hold_days is not None and self.max_hold_days is not None:
            if self.min_hold_days > self.max_hold_days:
                raise ValueError("最少持有天數不能大於最長持有天數")
        return self


class ModelSummaryOut(BaseModel):
    """模型列表用。realized/unrealized 兩個平均損益率都給，不預設哪個代表好壞。"""

    model_config = ConfigDict(protected_namespaces=())

    id: int
    model_family: str
    version: int
    model_type: str
    status: str
    is_archived: bool
    n_days: int
    threshold_percent: float
    label_mode: str = "absolute"
    label_mode_label: str = ""
    validation_mode: str = "single"
    feature_scaling: str = "zscore"
    feature_scaling_label: str = ""
    score_formula: str
    training_duration_seconds: float | None
    # 訓練途中才有值（階段、第幾個 epoch、當下的 loss），完成或失敗後回到 None
    training_progress: dict | None = None
    error_message: str | None
    created_at: datetime
    trained_at: datetime | None
    open_holding_count: int
    closed_holding_count: int
    average_realized_return_percent: float | None
    average_unrealized_return_percent: float | None


class ModelHoldingOut(BaseModel):
    stock_code: str
    stock_name: str
    entry_date: date
    entry_price: float
    exit_date: date | None
    exit_price: float | None
    status: str
    return_percent: float | None
    exit_reason: str | None
    held_days: int
    current_price: float | None


class ModelPredictionPointOut(BaseModel):
    predicted_return_percent: float
    actual_return_percent: float
    predicted_probability: float
    actual_label: bool


class CalibrationBucketOut(BaseModel):
    """分桶校準曲線的一個桶：預測機率落在這個區間的樣本，實際達標比例是多少。"""

    bucket_start: float
    bucket_end: float
    average_predicted: float
    actual_rate: float
    sample_count: int


class BacktestTradePointOut(BaseModel):
    entry_date: date
    return_percent: float
    stock_code: str
    exit_reason: str | None


class FeatureImportanceOut(BaseModel):
    feature: str
    label: str
    importance: float


class ScoringRunOut(BaseModel):
    run_date: date
    duration_seconds: float
    status: str


class ModelDetailOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    summary: ModelSummaryOut

    # 訓練參數（公開透明：讓看的人知道這個模型是怎麼練出來的）
    feature_config: list[str]
    feature_labels: list[str]
    min_hold_days: int | None
    max_hold_days: int | None
    stop_loss_percent: float | None
    take_profit_percent: float | None
    sell_conditions: list[dict]
    score_weights: dict | None
    score_formula_info: ScoreFormulaInfoOut
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    test_start: date
    test_end: date

    metrics: dict
    folds: list[FoldMetricsOut] = []
    walk_forward: WalkForwardSummaryOut | None = None
    warnings: list[str]
    network: NetworkInfoOut | None

    regression_points: list[ModelPredictionPointOut]
    calibration_buckets: list[CalibrationBucketOut]
    backtest_trades: list[BacktestTradePointOut]
    regression_feature_importance: list[FeatureImportanceOut]
    classification_feature_importance: list[FeatureImportanceOut]

    open_holdings: list[ModelHoldingOut]
    closed_holdings: list[ModelHoldingOut]
    scoring_runs: list[ScoringRunOut]
    average_scoring_seconds: float | None


class FeatureFlagOut(BaseModel):
    key: str
    label: str
    enabled: bool


class FeatureFlagUpdateIn(BaseModel):
    enabled: bool


class SchedulerFlagOut(BaseModel):
    """模型系統相關的排程開關。description 說明「關掉會發生什麼」，
    不然管理者只看得到一個名字，不敢動也不知道動了會怎樣。"""

    key: str
    label: str
    description: str
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
