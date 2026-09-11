export interface Stock {
  code: string;
  name: string;
  market: "TWSE" | "TPEX";
}

export interface Quote {
  code: string;
  name: string;
  price: number | null;
  prev_close: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  is_stale: boolean;
}

export interface Fundamentals {
  stock_code: string;
  pe_ratio: number | null;
  dividend_yield: number | null;
  pb_ratio: number | null;
  updated_at: string | null;
}

export interface FundamentalsHistoryPoint {
  as_of_date: string;
  pe_ratio: number | null;
  dividend_yield: number | null;
  pb_ratio: number | null;
}

export interface Account {
  id: number;
  name: string;
  cash_balance: number;
  frozen_cash: number;
  available_cash: number;
}

export interface Position {
  stock_code: string;
  stock_name: string;
  quantity: number;
  frozen_quantity: number;
  avg_cost: number;
  current_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
}

export type OrderSide = "buy" | "sell";
export type OrderStatus = "pending" | "filled" | "cancelled" | "expired";
export type OrderType = "limit" | "market" | "stop";

export interface Order {
  id: number;
  stock_code: string;
  side: OrderSide;
  order_type: OrderType;
  price: number;
  stop_price: number | null;
  quantity: number;
  status: OrderStatus;
  created_at: string;
  filled_at: string | null;
  filled_price: number | null;
}

export interface Trade {
  id: number;
  order_id: number;
  stock_code: string;
  side: OrderSide;
  price: number;
  quantity: number;
  amount: number;
  fee: number;
  tax: number;
  realized_pnl: number | null;
  executed_at: string;
}

export interface RealizedPnlSummary {
  total_realized_pnl: number;
  win_count: number;
  loss_count: number;
  win_rate: number | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  username: string;
  nickname: string;
  is_admin: boolean;
}

export interface AdminAccount {
  user_id: number;
  username: string;
  nickname: string;
  is_admin: boolean;
  cash_balance: number | null;
  frozen_cash: number | null;
  frozen_until: string | null;
  created_at: string;
}

export interface DailyBarBucket {
  label: string;
  count: number;
}

export interface DailyBarMarketStats {
  total_stocks: number;
  sufficient: number;
  insufficient: number;
  buckets: DailyBarBucket[];
}

export interface DailyBarStats {
  twse: DailyBarMarketStats;
  tpex: DailyBarMarketStats;
}

export type BackfillPhase =
  | "idle"
  | "preparing"
  | "running"
  | "throttling"
  | "rate_limited"
  | "completed"
  | "failed";

export interface BackfillProgress {
  job: string;
  job_label: string;
  phase: BackfillPhase;
  phase_label: string;
  current_target: string | null;
  processed: number;
  total: number;
  remaining_targets: number;
  written_bars: number;
  wait_seconds_remaining: number | null;
  wait_reason: string | null;
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface BackfillStatus {
  earliest_date: string | null;
  target_months: number;
  progress: BackfillProgress;
}

export type ModelType =
  | "xgboost"
  | "lightgbm"
  | "random_forest"
  | "logistic_regression"
  | "mlp"
  | "gru"
  | "lstm";
export type Activation = "relu" | "tanh" | "gelu";

export interface NetworkLayer {
  name: string;
  type: string;
  output_shape: string;
  params: number;
}

export interface LossCurvePoint {
  epoch: number;
  train_loss: number;
  validation_loss: number;
}

export interface NetworkInfo {
  layers: NetworkLayer[];
  total_params: number;
  loss_curve: LossCurvePoint[];
  device: string;
  epochs: number;
  hidden_sizes: number[];
  activation: string;
  dropout: number;
  /** 只有 GRU/LSTM 有：一個樣本往回看幾個交易日 */
  sequence_length: number | null;
  kind: string | null;
  /** 早停：原本設定跑幾輪、實際哪一輪最好（存下來的就是那一輪的權重） */
  configured_epochs: number | null;
  best_epoch: number | null;
  early_stopped: boolean;
  patience: number | null;
  batch_size: number | null;
}

export interface TreeConfigInput {
  n_estimators: number;
  max_depth: number;
  learning_rate: number;
  subsample: number;
  colsample: number;
  min_child_samples: number;
  /** 訓練用幾個執行緒。記憶體用量大致跟著它走，調大之前先看資源餘裕 */
  n_jobs: number;
}

export interface NetworkConfigInput {
  hidden_sizes: number[];
  activation: Activation;
  dropout: number;
  learning_rate: number;
  epochs: number;
  sequence_length: number;
  patience: number;
  batch_size: number;
}
export type LabelMode = "absolute" | "excess";
export type ValidationMode = "single" | "walk_forward";
export type FeatureScaling = "zscore" | "cross_sectional_rank";

export interface WalkForwardConfigInput {
  train_months: number;
  validation_months: number;
  test_months: number;
  step_months: number;
}

export interface WalkForwardStat {
  mean: number;
  std: number;
  min: number;
  max: number;
  positive_folds: number;
  count: number;
}

export interface WalkForwardSummary {
  fold_count: number;
  test_rank_ic: WalkForwardStat | null;
  test_auc: WalkForwardStat | null;
  validation_rank_ic: WalkForwardStat | null;
}

export interface FoldMetrics {
  fold: {
    index: number;
    train_start: string;
    train_end: string;
    validation_start: string;
    validation_end: string;
    test_start: string;
    test_end: string;
  };
  train: Record<string, number | null>;
  validation: Record<string, number | null>;
  test: Record<string, number | null>;
}

export type ScoreFormula = "multiply" | "zscore_weighted";
export type ModelStatus = "queued" | "training" | "completed" | "failed";

export interface FeatureOption {
  key: string;
  label: string;
}

export interface ModelTypeOption {
  key: ModelType;
  label: string;
  is_neural: boolean;
  is_sequence: boolean;
  is_tree: boolean;
  /** 隨機森林沒有學習率 */
  has_learning_rate: boolean;
}

export interface ScoreFormulaInfo {
  key: string;
  name: string;
  formula: string;
  definition: string;
  summary: string;
  reasons: string[];
  limitation: string;
}

export interface FeaturePreset {
  key: string;
  label: string;
  description: string;
  features: string[];
}

export interface TrainDefaults {
  latest_data_date: string | null;
  train_start: string;
  train_end: string;
  validation_start: string;
  validation_end: string;
  test_start: string;
  test_end: string;
  default_features: string[];
  feature_presets: FeaturePreset[];
  features: FeatureOption[];
  model_types: ModelTypeOption[];
  score_formula: ScoreFormulaInfo;
}

export interface ModelTrainRequest {
  model_family: string;
  model_type: ModelType;
  feature_config: string[];
  n_days: number;
  threshold_percent: number;
  label_mode: LabelMode;
  validation_mode: ValidationMode;
  feature_scaling: FeatureScaling;
  industry_neutral: boolean;
  /** 分數低於這個值就不買；null 表示不設限 */
  min_score?: number | null;
  walk_forward_config?: WalkForwardConfigInput | null;
  score_weights?: { return: number; probability: number } | null;
  network_config?: NetworkConfigInput | null;
  tree_config?: TreeConfigInput | null;
  min_hold_days?: number | null;
  max_hold_days?: number | null;
  stop_loss_percent?: number | null;
  take_profit_percent?: number | null;
  sell_conditions: Condition[];
  train_start: string;
  train_end: string;
  validation_start: string;
  validation_end: string;
  test_start: string;
  test_end: string;
}

export interface ModelHoldingItem {
  stock_code: string;
  stock_name: string;
  entry_date: string;
  entry_price: number;
  exit_date: string | null;
  exit_price: number | null;
  status: "open" | "closed";
  return_percent: number | null;
  exit_reason: string | null;
  held_days: number;
  current_price: number | null;
}

export interface ModelPredictionPoint {
  predicted_return_percent: number;
  actual_return_percent: number;
  predicted_probability: number;
  actual_label: boolean;
}

export interface CalibrationBucket {
  bucket_start: number;
  bucket_end: number;
  average_predicted: number;
  actual_rate: number;
  sample_count: number;
}

export interface BacktestTradePoint {
  entry_date: string;
  return_percent: number;
  stock_code: string;
  exit_reason: string | null;
}

export interface FeatureImportance {
  feature: string;
  label: string;
  importance: number;
}

export interface ScoringRun {
  run_date: string;
  duration_seconds: number;
  status: string;
}

export interface ModelDetail {
  summary: ModelSummary;
  feature_config: string[];
  feature_labels: string[];
  min_hold_days: number | null;
  max_hold_days: number | null;
  stop_loss_percent: number | null;
  take_profit_percent: number | null;
  sell_conditions: Condition[];
  score_weights: { return: number; probability: number } | null;
  score_formula_info: ScoreFormulaInfo;
  train_start: string;
  train_end: string;
  validation_start: string;
  validation_end: string;
  test_start: string;
  test_end: string;
  metrics: Record<string, any> | null;
  folds: FoldMetrics[];
  walk_forward: WalkForwardSummary | null;
  warnings: string[];
  network: NetworkInfo | null;
  regression_points: ModelPredictionPoint[];
  calibration_buckets: CalibrationBucket[];
  backtest_trades: BacktestTradePoint[];
  regression_feature_importance: FeatureImportance[];
  classification_feature_importance: FeatureImportance[];
  open_holdings: ModelHoldingItem[];
  closed_holdings: ModelHoldingItem[];
  scoring_runs: ScoringRun[];
  average_scoring_seconds: number | null;
}

export interface ModelSummary {
  id: number;
  model_family: string;
  version: number;
  model_type: ModelType;
  status: ModelStatus;
  /** 佇列裡前面還卡著幾筆。0 = 正在跑，null = 不在佇列裡 */
  queue_position: number | null;
  is_archived: boolean;
  n_days: number;
  threshold_percent: number;
  label_mode: string;
  label_mode_label: string;
  validation_mode: string;
  feature_scaling: string;
  feature_scaling_label: string;
  industry_neutral: boolean;
  min_score: number | null;
  score_formula: ScoreFormula;
  training_duration_seconds: number | null;
  /** 訓練途中才有值，完成或失敗後回到 null */
  training_progress: TrainingProgress | null;
  error_message: string | null;
  created_at: string;
  trained_at: string | null;
  open_holding_count: number;
  closed_holding_count: number;
  average_realized_return_percent: number | null;
  average_unrealized_return_percent: number | null;
  /** 目前持有的整體損益率：總市值比總成本（每檔各一股，價格加權） */
  total_unrealized_return_percent: number | null;

  /** 滾動驗證時是各折平均；單次切分時是那一次的測試分數 */
  test_rank_ic: number | null;
  test_rank_ic_std: number | null;
  test_auc: number | null;
  fold_count: number | null;
  positive_folds: number | null;
  backtest_average_return_percent: number | null;
  backtest_win_rate: number | null;
  backtest_holding_count: number | null;
}

export interface SchedulerFlag {
  key: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface FeatureFlag {
  key: string;
  label: string;
  enabled: boolean;
}

export interface LeaderboardEntry {
  nickname: string;
  total_assets: number;
  cash_balance: number;
  market_value: number;
}

export type MarketSessionStatus = "trading" | "after_hours" | "closed";

export interface MarketSession {
  status: MarketSessionStatus;
  trading_start: string;
  trading_end: string;
  after_hours_end: string;
}

export interface DailyBar {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PricePoint {
  ts: string;
  price: number;
}

export interface WatchlistItem {
  stock_code: string;
  stock_name: string;
  market: "TWSE" | "TPEX";
  created_at: string;
  current_price: number | null;
}

export type NumericOperator = "gt" | "lt" | "gte" | "lte";
export type CrossDirection = "golden" | "death";
export type MaPeriod = 5 | 20 | 60;

export interface KdValueCondition {
  type: "kd_value";
  line: "k" | "d";
  operator: NumericOperator;
  value: number;
}

export interface KdCrossCondition {
  type: "kd_cross";
  direction: CrossDirection;
}

export interface MaCompareCondition {
  type: "ma_compare";
  fast: MaPeriod;
  slow: MaPeriod;
  operator: "gt" | "lt";
}

export interface PriceVsMaCondition {
  type: "price_vs_ma";
  period: MaPeriod;
  operator: "gt" | "lt";
}

export interface StreakCondition {
  type: "streak";
  direction: "up" | "down";
  days: number;
}

export interface CumulativeChangeCondition {
  type: "cumulative_change";
  days: number;
  operator: "gte" | "lte";
  percent: number;
}

export type Condition =
  | KdValueCondition
  | KdCrossCondition
  | MaCompareCondition
  | PriceVsMaCondition
  | StreakCondition
  | CumulativeChangeCondition;

export type RankBy = "change_percent" | "k_value" | "d_value" | "volume";
export type RankDirection = "asc" | "desc";

export interface StrategyInput {
  name: string;
  quantity: number;
  buy_conditions: Condition[];
  sell_conditions: Condition[];
  rank_by: RankBy;
  rank_direction: RankDirection;
  top_n: number;
}

export interface Strategy extends StrategyInput {
  id: number;
  is_active: boolean;
  created_at: string;
}

export interface StrategyTradeRecord {
  id: number;
  stock_code: string;
  stock_name: string;
  side: OrderSide;
  trade_date: string;
  price: number | null;
  quantity: number | null;
  status: OrderStatus | null;
}

export interface EquitySnapshot {
  snapshot_date: string;
  cash_balance: number;
  market_value: number;
  total_assets: number;
}

export interface BacktestRequest {
  start_date: string;
  end_date: string;
  initial_cash: number;
}

export interface EquityCurvePoint {
  date: string;
  total_assets: number;
}

export interface BacktestResult {
  start_date: string;
  end_date: string;
  initial_cash: number;
  final_assets: number;
  total_return_percent: number;
  max_drawdown_percent: number;
  trade_count: number;
  win_count: number;
  loss_count: number;
  win_rate: number | null;
  equity_curve: EquityCurvePoint[];
  warning: string | null;
}

/** 模型教學頁的資料來源。內容全部來自後端實作，前端不自己抄一份系統設定。 */
export interface ModelCatalog {
  model_types: ModelTypeOption[];
  score_formula: ScoreFormulaInfo;
  features: FeatureOption[];
  /** 每天最多持有幾檔 */
  top_n: number;
  commission_rate: number;
  tax_rate: number;
}

export interface TrainingProgress {
  /** preparing = 組特徵切分資料、training = 跑 epoch、backtesting = 回測 */
  phase: "preparing" | "training" | "backtesting";
  updated_at: string;
  epoch?: number;
  total_epochs?: number | null;
  train_loss?: number;
  validation_loss?: number;
  best_epoch?: number;
  best_validation_loss?: number | null;
}

export interface ModelDeleteResult {
  deleted: boolean;
  model_id: number;
  label: string;
  deleted_predictions: number;
  deleted_holdings: number;
  deleted_scoring_runs: number;
  removed_artifact: boolean;
}

export interface ChipStatus {
  earliest_date: string | null;
  latest_date: string | null;
  total_rows: number;
  progress: BackfillProgress;
}

export interface ShareholdingStatus {
  earliest_date: string | null;
  latest_date: string | null;
  total_rows: number;
  /** 週頻資料，所以看的是累積了幾週而不是幾天 */
  week_count: number;
  message: string | null;
}

export interface IndustryStatus {
  total_stocks: number;
  /** ETF 與受益證券沒有產業別，所以一定小於 total_stocks */
  classified: number;
  industry_count: number;
  top_industries: { code: string; label: string; count: number }[];
  message: string | null;
}
