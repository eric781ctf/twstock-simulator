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
