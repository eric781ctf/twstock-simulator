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
  phase: BackfillPhase;
  phase_label: string;
  current_stock_code: string | null;
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

export type ModelType = "xgboost" | "lightgbm" | "random_forest" | "logistic_regression";
export type ScoreFormula = "multiply" | "zscore_weighted";
export type ModelStatus = "queued" | "training" | "completed" | "failed";

export interface FeatureOption {
  key: string;
  label: string;
}

export interface ModelTypeOption {
  key: ModelType;
  label: string;
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
  features: FeatureOption[];
  model_types: ModelTypeOption[];
}

export interface ModelTrainRequest {
  model_family: string;
  model_type: ModelType;
  feature_config: string[];
  n_days: number;
  threshold_percent: number;
  score_formula: ScoreFormula;
  score_weights?: { return: number; probability: number } | null;
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
  train_start: string;
  train_end: string;
  validation_start: string;
  validation_end: string;
  test_start: string;
  test_end: string;
  metrics: Record<string, any> | null;
  warnings: string[];
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
  is_archived: boolean;
  n_days: number;
  threshold_percent: number;
  score_formula: ScoreFormula;
  training_duration_seconds: number | null;
  error_message: string | null;
  created_at: string;
  trained_at: string | null;
  open_holding_count: number;
  closed_holding_count: number;
  average_realized_return_percent: number | null;
  average_unrealized_return_percent: number | null;
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
