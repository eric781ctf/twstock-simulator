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


class Stock(Base):
    __tablename__ = "stocks"

    code: Mapped[str] = mapped_column(String(10), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    market: Mapped[Market] = mapped_column(Enum(Market), nullable=False)
    # TWSE 產業別代碼（24=半導體…）。只用來做產業中性化的分組；
    # ETF 與受益證券沒有產業別，維持 NULL
    industry: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
    # 預測的是絕對報酬還是超額報酬（減掉大盤）。舊模型沒有這個欄位，
    # 取不到就是 absolute——它們當初訓練時本來就是那樣算的
    label_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="absolute")
    # 什麼時候成交，以及 label 量的是哪一段價格。
    #
    # close      收盤決策、收盤成交：label = 收盤(D) → 收盤(D+n)
    # next_open  盤前決策、開盤成交：label = 開盤(D+1) → 開盤(D+1+n)
    #
    # 差別不只是「換一個價格欄位」。next_open 把決策時點移到 09:00 之前，
    # 於是前一晚的美股與台指期夜盤變成可用的資訊——那是 close 模式拿不到的
    # （在 close 模式下，夜盤發生在成交之後）。代價是兩種模式的 label 量的是
    # 不同的區間，績效數字**不能互相比較**，換模式等於要重建基準。
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="close")

    # 選股分數一律用橫斷面標準化加權（見 services/ml/train.py 的 SCORE_FORMULA_INFO）
    score_formula: Mapped[str] = mapped_column(String(20), nullable=False, default="zscore_weighted")
    score_weights: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 神經網路類型才會用到：層數與每層神經元數、啟用函數、dropout、epochs 等
    network_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 樹模型的超參數（棵數、深度、學習率、抽樣比例…）
    tree_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 驗證方式：single（單次固定切分）或 walk_forward（滾動視窗多折）
    validation_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="single")
    # 滾動視窗的各段月數與步長
    walk_forward_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 特徵標準化方式：zscore（用訓練期的平均/標準差）或
    # cross_sectional_rank（每天換算成全市場分位數）
    feature_scaling: Mapped[str] = mapped_column(String(30), nullable=False, default="zscore")
    # 是否把特徵減掉當天同產業的中位數
    industry_neutral: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 選股分數的下限。低於這個分數就不買，寧可持股不滿。分數是當天全市場的
    # z-score 加權平均，所以 0 = 當天平均水準，門檻是相對的而不是絕對報酬
    min_score: Mapped[float | None] = mapped_column(Float, nullable=True)

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
    # 訓練途中的進度（階段、第幾個 epoch、當下的 loss）。訓練跑在獨立的 process 裡，
    # 這是它跟 API 之間唯一的溝通管道——每個 epoch 各 commit 一次，admin 頁面輪詢就看得到。
    training_progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_artifact_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    trained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChipDaily(Base):
    """每檔股票、每個交易日的籌碼面資料（三大法人買賣超與信用交易餘額）。

    台股外資持股比重高，法人買賣超是這個市場長期被討論最多的訊號之一。
    資料來自 TWSE 每日公開的 T86（三大法人買賣超日報）與 MI_MARGN（融資融券），
    兩支都是「一次一天、拿全市場」，跟日K回補走同一種請求形狀。

    單位保持 TWSE 原始的樣子：法人買賣超是「股數」，信用交易餘額是「交易單位
    （張）」。兩者不換算成同一單位——特徵那邊本來就要各自除以成交量或前值做
    正規化，先換算只會多一次無意義的乘除。
    """

    __tablename__ = "chip_daily"
    __table_args__ = (UniqueConstraint("stock_code", "trade_date", name="uq_chip_daily_code_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # 買賣超股數，正數是買超。外資這欄不含外資自營商，跟 TWSE 的主要欄位一致
    foreign_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    trust_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    dealer_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    institution_net: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 信用交易餘額（張）。融資餘額常被當成散戶槓桿的代理
    margin_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    short_balance: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 外資持股比率（%）。跟買賣超是不同性質的東西：買賣超是「今天流入多少」，
    # 持股比率是「累積下來外資手上有多少」——存量與流量互補
    foreign_holding_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)


class ShareholdingWeekly(Base):
    """集保戶股權分散表的每週快照，已收斂成散戶／中實戶／大戶三組。

    原始資料每檔股票有 17 個持股分級，但特徵真正用得到的是「籌碼集中在誰手上」，
    所以入庫時就聚合掉——存 17 個分級只是把同一個判斷推遲到查詢時做。
    分級 17 是「合計」列，聚合時排除，不然每個比例都會變成兩倍。

    週頻資料（每週五快照，隔天發布）。特徵那邊要用「日期嚴格早於特徵日」的
    最後一筆，否則會在週五當天看到還沒公布的數字。
    """

    __tablename__ = "shareholding_weekly"
    __table_args__ = (
        UniqueConstraint("stock_code", "as_of_date", name="uq_shareholding_code_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("stocks.code"), nullable=False, index=True)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    total_holders: Mapped[int] = mapped_column(Integer, nullable=False)
    # 散戶：不到 10 張
    retail_holders: Mapped[int] = mapped_column(Integer, nullable=False)
    retail_share_percent: Mapped[float] = mapped_column(Float, nullable=False)
    # 中實戶：400~800 張
    mid_holders: Mapped[int] = mapped_column(Integer, nullable=False)
    mid_share_percent: Mapped[float] = mapped_column(Float, nullable=False)
    # 大戶：超過 1000 張
    big_holders: Mapped[int] = mapped_column(Integer, nullable=False)
    big_share_percent: Mapped[float] = mapped_column(Float, nullable=False)


class FuturesDaily(Base):
    """台指期／電子期的每日行情，日盤與夜盤分開存。

    夜盤（期交所叫「盤後交易時段」）是這張表存在的理由：它的交易時間是
    15:00 到隔日 05:00，**完整涵蓋美股盤中**。台股現貨在美股開盤時是休市的，
    所以「美股隔夜怎麼走」對台股的影響，在現貨價格上要等到隔天 09:00 才看得到，
    但在台指期夜盤上是即時反映的。

    **日期歸屬要特別小心。** 期交所把「D−1 日 15:00 開始、D 日 05:00 結束」的
    那一節標成日期 D。實測驗證方式是比對盤後開盤價跟前後日的日盤收盤價——
    2020 與 2024 抽樣都顯示盤後開盤價貼近**前一日**日盤收盤（差 0~16 點），
    而距同日日盤收盤動輒 100~300 點。

    所以 session='night' 且 trade_date=D 的那一列，其資訊在 D 日 05:00 就已經
    確定，早於 D 日 09:00 開盤——拿來當 D 日的特徵不會有 look-ahead。
    """

    __tablename__ = "futures_daily"
    __table_args__ = (
        UniqueConstraint("contract", "trade_date", "session", name="uq_futures_contract_date_session"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # TX=臺股期貨、TE=電子期貨。只存近月，遠月流動性低、價格代表性差
    contract: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # day=一般交易時段、night=盤後交易時段
    session: Mapped[str] = mapped_column(String(10), nullable=False)

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    open_interest: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


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


