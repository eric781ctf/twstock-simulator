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

export interface Order {
  id: number;
  stock_code: string;
  side: OrderSide;
  price: number;
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
  executed_at: string;
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
